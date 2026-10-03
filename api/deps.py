"""
API için merkezi bağımlılık yönetimi.

PluginManager, ExtractorManager gibi paylaşılan kaynakları sağlar.
Ayrıca Supabase (senkronizasyon) ve Supabase Auth istemcilerini yönetir ve
`Authorization: Bearer <token>` doğrulamasını FastAPI'nin `Depends` mekanizması
üzerinden sunar.

Not: `Depends` ve `response_model` bu dosyada bilinçli bir konvansiyon
istisnasıdır (SYNC_AUTH_PLAN.md §4.2). Gerekçesi: token gövdesi ve senkron
red/kabul semantiği gizli kalmamalı, OpenAPI şeması belgelemelidir.
"""

from __future__ import annotations

import os
from typing import Annotated, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from Core.Plugin.PluginManager import PluginManager
from Core.Extractor.ExtractorManager import ExtractorManager
from Core.Helpers.Kontrol import MainUrlGuncelleyici
from Core.Helpers.TMDBEnricher import TMDBEnricher
from Core.Libs.Supabase import SupabaseManager
from Core.Libs.SupabaseAuth import (
    InvalidTokenError,
    SupabaseAuthManager,
    AuthConfigurationError,
)
from Core.Libs.TMDB import TMDBClient

# ── Paylaşılan HTTP durum sabitleri ──────────────────────────────────────────
# Starlette sürümleri arasında bu sabitlerin adı değişebiliyor
# (UNPROCESSABLE_ENTITY ↔ UNPROCESSABLE_CONTENT, ENTITY_TOO_LARGE ↔
# CONTENT_TOO_LARGE). Sürümden bağımsız olmak için durum kodları doğrudan yazılır.

# Gövde doğrulama hatası
HTTP_422_INVALID_BODY = 422

# Gövde çok büyük / karşılaştırma tavası aşıldı
HTTP_413_TOO_LARGE = 413

# ── Uygulama başlatıldığında bir kez oluşturulan tekil (singleton) nesneler ──

_plugin_manager: PluginManager | None = None
_extractor_manager: ExtractorManager | None = None
_supabase_manager: SupabaseManager | None = None
_auth_manager: SupabaseAuthManager | None = None
_tmdb_client: TMDBClient | None = None
_tmdb_enricher: TMDBEnricher | None = None

# Bearer şeması: `Authorization` başlığı yoksa 403 yerine 401 döner.
_bearer_scheme = HTTPBearer(auto_error=False)


def get_plugin_manager() -> PluginManager:
    """Plugin yöneticisini döndürür (lazy singleton)."""
    global _plugin_manager
    if _plugin_manager is None:
        # URL'leri başlatmadan önce güncelle
        guncelleyici = MainUrlGuncelleyici()
        guncelleyici.guncelle()
        _plugin_manager = PluginManager()
    return _plugin_manager


def get_extractor_manager() -> ExtractorManager:
    """Extractor yöneticisini döndürür (lazy singleton)."""
    global _extractor_manager
    if _extractor_manager is None:
        _extractor_manager = ExtractorManager()
    return _extractor_manager


def get_supabase_async() -> SupabaseManager:
    """Senkronizasyon veri yöneticisini döndürür (lazy singleton)."""
    global _supabase_manager
    if _supabase_manager is None:
        _supabase_manager = SupabaseManager()
    return _supabase_manager


def get_auth_manager() -> SupabaseAuthManager:
    """Supabase Auth yöneticisini döndürür (lazy singleton)."""
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = SupabaseAuthManager()
    return _auth_manager


def get_tmdb_client() -> TMDBClient:
    """TMDB istemcisini döndürür (lazy singleton).

    `TMDB_API_KEY` tanımlı değilse istem "devre dışı" kalır: tüm metotlar
    ücretsizce `None` döner ve API uçları yalnızca eklenti verisiyle çalışır.
    """
    global _tmdb_client
    if _tmdb_client is None:
        _tmdb_client = TMDBClient()
    return _tmdb_client


def get_tmdb_enricher() -> TMDBEnricher:
    """Görsel zenginleştiriciyi döndürür (lazy singleton)."""
    global _tmdb_enricher
    if _tmdb_enricher is None:
        eszamanlilik = int(os.getenv("TMDB_ENRICH_CONCURRENCY", "5"))
        zorunlu = os.getenv("TMDB_ENRICH_STRICT", "0").strip().lower() in ("1", "true", "yes", "on")
        _tmdb_enricher = TMDBEnricher(get_tmdb_client(), eszamanlilik, zorunlu)
    return _tmdb_enricher


# ── Kimlik doğrulama bağımlılığı ─────────────────────────────────────────────

Credentials = Annotated[Optional[HTTPAuthorizationCredentials], Depends(_bearer_scheme)]


def _unauthorized(detail: str = "Oturum geçersiz.") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_claims(credentials: Credentials) -> dict:
    """
    `Authorization: Bearer <access_token>` başlığını doğrular ve JWT iddialarını döner.

    Dönüş: `{"sub": ..., "email": ..., "role": ..., "source": "jwt"|"gotrue"}`

    Başlık yoksa veya token geçersizse 401 fırlatır. Frontend bu durumda
    sessizce `POST /api/auth/refresh` dener; başarısızsa oturumu kapatır.
    """
    if credentials is None or not credentials.credentials:
        raise _unauthorized()

    try:
        claims = await get_auth_manager().verify_access_token(credentials.credentials)
    except InvalidTokenError:
        raise _unauthorized()
    except AuthConfigurationError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Kimlik doğrulama servisi yapılandırılmamış: {e}",
        )

    if not claims.get("sub"):
        raise _unauthorized()
    return claims


async def get_current_user(claims: Annotated[dict, Depends(get_current_claims)]) -> str:
    """Doğrulanmış kullanıcının `auth.users.id` değerini döndürür."""
    return str(claims["sub"])


async def get_optional_token(credentials: Credentials) -> Optional[str]:
    """
    `Authorization` başlığından ham token'ı döner; yoksa None.

    Yalnızca `POST /api/auth/logout` kullanır: çıkışta token geçersiz olsa bile
    istek 401 dönmemeli, çünkü istemci token'ları zaten silmek üzeredir.
    """
    return credentials.credentials if credentials else None


CurrentUser = Annotated[str, Depends(get_current_user)]
CurrentClaims = Annotated[dict, Depends(get_current_claims)]
OptionalToken = Annotated[Optional[str], Depends(get_optional_token)]
