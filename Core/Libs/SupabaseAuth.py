"""
Supabase Auth (GoTrue) async sarmalayıcı + JWT doğrulama.

Neden Supabase Auth:
    Parola hash'leme, JWT imzalama, token yenileme ve refresh rotation hazır
    gelir; `supabase` zaten bağımlılıktır. Sıfır yeni bağımlılık.

JWT doğrulama — güncel anahtar modeli
------------------------------------
Supabase artık iki imza sistemini destekliyor:

  * **Asimetrik (RSA / ECC P-256 / EdDSA)** — önerilen yol. Token'lar bir
    `kid` başlığıyla imzalanır; açık anahtarlar projenin JWKS uç noktasında
    yayımlanır. Doğrulama tamamen yerelde ve ağ turu olmadan yapılabilir.
  * **Simetrik (HS256, "Legacy JWT Secret")** — geriye uyum. Paylaşılan sır
    JWKS'te YAYIMLANMAZ, dolayısıyla yerel doğrulama için o sır gerekir;
    Supabase bu yaklaşıma karşı açıkça uyarır (sızma riski, SOC2 uyumsuzluğu).

Bu modül bu ayrımı kendisi yönetmez; SDK'nın resmî `auth.get_claims()` metoduna
devreder. O metot token başlığındaki `alg`/`kid` değerine bakar ve:

    alg == HS256 (veya `kid` yoksa) → Auth sunucusuna gider (`get_user`)
    aksi hâlde                     → JWKS'ten `kid` ile eşleşen açık anahtarı
                                     bulur ve imzayı YERELDE doğrular

Sonuç: **hiçbir anahtarı `.env`'e koymaya gerek yoktur**, anahtar döndürme
(rotation) ve iptal (revocation) kod değişikliği gerektirmez, ve proje asimetrik
anahtara geçtiğinde uygulama otomatik olarak ağ turusuz moda düşer.

Referans: supabase.com/docs/guides/auth/jwts ve /guides/auth/signing-keys
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from typing import Any, Dict, Optional

from supabase import AsyncClient, acreate_client
from supabase_auth.errors import AuthApiError, AuthError, AuthInvalidJwtError

from Core.Helpers.Cli import debug_log


class AuthConfigurationError(RuntimeError):
    """Supabase Auth yapılandırması eksik veya geçersiz."""


class InvalidTokenError(Exception):
    """Bearer token geçersiz, süresi dolmuş veya kullanıcı bulunamadı."""


# Erişim token'larının `role` iddiası sabittir; `service_role` JWT'leri
# (örneğin yanlışlıkla sızan sunucu anahtarı) kabul edilmez.
_EXPECTED_ROLE = "authenticated"

# Simetrik imza: JWKS'te yayımlanmadığı için yerel doğrulanamaz.
_SYMMETRIC_ALG = "HS256"


def resolve_supabase_url() -> str:
    return (os.getenv("SUPABASE_URL") or "").strip()


def resolve_anon_key() -> str:
    """
    GoTrue istemci anahtarını çözer (`SUPABASE_ANON_KEY`).

    Bu anahtar SADECE kimlik doğrulama (GoTrue) çağrıları için kullanılır;
    PostgREST yazmalarında kullanılmaz.
    """
    return (os.getenv("SUPABASE_ANON_KEY") or "").strip()


def resolve_service_role_key() -> tuple[str, str]:
    """
    Sunucu (PostgREST) anahtarını çözer.

    Dönüş: `(anahtar, değişken_adı)` — anahtar yoksa `("", "")`.

    🔴 Yedek anahtar zinciri YOKTUR. `user_library` / `user_documents`
    tablolarında RLS açık, politika yoktur; anon anahtarla yapılan her sorgu
    boş döner ve senkronizasyon HTTP 200 görünürlüğünde sessizce hiçbir şey
    taşımaz. Bu nedenle eksik anahtar sessizce telafi edilmez, çağıran taraf
    açık bir hata fırlatır.
    """
    name = "SUPABASE_SERVICE_ROLE_KEY"
    return ((os.getenv(name) or "").strip(), name)


class SupabaseAuthManager:
    """GoTrue işlemleri ve token doğrulama için tek giriş noktası."""

    def __init__(
        self,
        url: Optional[str] = None,
        anon_key: Optional[str] = None,
    ) -> None:
        self.url = (url if url is not None else resolve_supabase_url()).strip()
        self.anon_key = (
            anon_key if anon_key is not None else resolve_anon_key()
        ).strip()
        self._client: Optional[AsyncClient] = None

    # ── İstemci ──────────────────────────────────────────────────────────────

    async def client(self) -> AsyncClient:
        """Async GoTrue istemcisini döndürür (lazy singleton)."""
        if self._client is None:
            if not self.url:
                raise AuthConfigurationError(
                    "SUPABASE_URL tanımlı değil. .env dosyasını kontrol edin."
                )
            if not self.anon_key:
                raise AuthConfigurationError(
                    "SUPABASE_ANON_KEY tanımlı değil. "
                    "Supabase Dashboard → Settings → API bölümünden kopyalayın."
                )
            try:
                self._client = await acreate_client(self.url, self.anon_key)
            except Exception as e:
                raise AuthConfigurationError(
                    f"Supabase Auth istemcisi oluşturulamadı: {e}"
                )
        return self._client

    async def close(self) -> None:
        """Açık HTTP bağlantılarını kapatır (lifespan shutdown)."""
        if self._client is not None:
            for closer in (
                getattr(self._client.auth, "close", None),
                getattr(getattr(self._client, "postgrest", None), "aclose", None),
            ):
                if closer is None:
                    continue
                try:
                    await closer()
                except Exception as e:  # kapanış hatası kritik değildir
                    debug_log("Auth istemcisi kapatılırken hata:", e)
            self._client = None

    # ── Kayıt / giriş / yenileme / çıkış ────────────────────────────────────

    async def sign_up(
        self,
        email: str,
        password: str,
        username: str,
        display_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Yeni kullanıcı kaydeder ve oturum token'larıyla döner.

        `username` ve `display_name` GoTrue `user_metadata` alanına taşınır;
        `user_profiles` satırı route katmanında oluşturulur.
        """
        metadata: Dict[str, Any] = {"username": username}
        if display_name:
            metadata["display_name"] = display_name

        client = await self.client()
        try:
            response = await client.auth.sign_up(
                {"email": email, "password": password, "options": {"data": metadata}}
            )
        except AuthApiError as e:
            raise AuthApiError(_tr_message(e), getattr(e, "status", 400), getattr(e, "code", None))
        except AuthError as e:
            raise RuntimeError(str(e))

        return _session_payload(response)

    async def sign_in(self, email: str, password: str) -> Dict[str, Any]:
        """
        E-posta + parola ile giriş yapar.

        Hatalı bilgiler daima **400** olarak fırlatılır. GoTrue'nin durum kodu
        sürümden sürüme değişebildiği için (`invalid_credentials` için 400 ya da
        401) burada sabitlenir: 401, istemcide "oturum süresi doldu → refresh →
        çıkış yap" anlamına gelir ve yanlış parolada kullanıcıyı ekranından
        atar.
        """
        client = await self.client()
        try:
            response = await client.auth.sign_in_with_password(
                {"email": email, "password": password}
            )
        except AuthApiError as e:
            status = 400 if (getattr(e, "code", None) in _CREDENTIAL_ERROR_CODES
                             or getattr(e, "status", 400) in (400, 401)) \
                else getattr(e, "status", 400)
            raise AuthApiError(_tr_message(e), status, getattr(e, "code", None))
        except AuthError as e:
            raise RuntimeError(str(e))

        return _session_payload(response)

    async def refresh(self, refresh_token: str) -> Dict[str, Any]:
        """Refresh token ile yeni bir erişim token'ı üretir (rotation)."""
        client = await self.client()
        try:
            response = await client.auth.refresh_session(refresh_token)
        except AuthApiError as e:
            raise AuthApiError(_tr_message(e), getattr(e, "status", 401), getattr(e, "code", None))
        except AuthError as e:
            raise RuntimeError(str(e))

        return _session_payload(response)

    async def logout(self, access_token: str) -> None:
        """
        GoTrue tarafındaki oturumu kapatır (refresh token iptali).

        Hata durumunda yutulur: istemci token'ları her hâlükârda siler ve
        "çıkış" kullanıcı açısından yine de gerçekleşmiş olur.
        """
        if not access_token:
            return
        client = await self.client()
        try:
            http = client.auth._http_client  # supabase_auth bunu yönetir
            await http.post(
                f"{self.url.rstrip('/')}/auth/v1/logout",
                params={"scope": "local"},
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "apikey": self.anon_key,
                },
            )
        except Exception as e:
            debug_log("GoTrue logout çağrısı başarısız (yutuldu):", e)

    # ── Kurulum teşhisi ──────────────────────────────────────────────────────

    async def probe_verification_mode(self) -> Dict[str, Any]:
        """
        Projenin imza modelini belirler: asimetrik mi, simetrik mi?

        JWKS uç noktası yalnızca ASİMETRİK anahtarları yayımlar. Dolayısıyla
        yanıt doluysa doğrulama ağ turusuz (yerel) yapılıyor, boşsa her istek
        Auth sunucusuna gidiyor demektir.

        Dönüş:
            `{"mode": "asymmetric"|"symmetric"|"unknown", "key_count": N,
               "algorithms": [...], "key_ids": [...], "reason": "..."}`

        Tanı AMAÇLIDIR; başarısız olursa `mode="unknown"` döner ve çağıran bunu
        yutmalıdır — başlangıcı engellememelidir.
        """
        if not self.url:
            return {"mode": "unknown", "reason": "SUPABASE_URL tanımlı değil."}
        if not self.anon_key:
            return {"mode": "unknown", "reason": "SUPABASE_ANON_KEY tanımlı değil."}

        endpoint = f"{self.url.rstrip('/')}/auth/v1/.well-known/jwks.json"

        try:
            client = await self.client()
            response = await client.auth._http_client.get(
                endpoint, headers={"apikey": self.anon_key}
            )
            if response.status_code != 200:
                return {
                    "mode": "unknown",
                    "reason": f"JWKS uç noktası HTTP {response.status_code} döndü.",
                }
            keys = (response.json() or {}).get("keys") or []
        except Exception as e:
            return {"mode": "unknown", "reason": str(e)}

        return {
            "mode": "asymmetric" if keys else "symmetric",
            "key_count": len(keys),
            "algorithms": sorted({str(k.get("alg")) for k in keys if k.get("alg")}),
            "key_ids": [str(k.get("kid")) for k in keys if k.get("kid")],
        }

    # ── Token doğrulama ──────────────────────────────────────────────────────

    async def verify_access_token(self, token: str) -> Dict[str, Any]:
        """
        Access token'ı doğrular ve standart iddialar kümesini döndürür.

        Doğrulama SDK'nın resmî `auth.get_claims()` metoduna devredilir; o metot
        token'ın imza algoritmasına göre yolu seçer:

            ES256 / RS256 / EdDSA → JWKS'ten `kid` ile eşleşen açık anahtarı
                                   bulur, imzayı YERELDE doğrular (ağ turu yok)
            HS256                 → Auth sunucusuna gider (ağ turu ~20-40 ms)

        `exp` her iki yolda da yerelde denetlenir. `role` denetimi BURADA
        yapılır: `service_role` JWT'leri (örneğin yanlışlıkla sızan sunucu
        anahtarı) kabul edilmez.

        Dönüş: `{"sub":..., "email":..., "role":..., "source": "jwks"|"gotrue"}`
        Hata: `InvalidTokenError`

        `AuthConfigurationError` BİLEREK yutulmaz — sunucu yapılandırması eksikse
        bu bir "geçersiz token" değil, 503'e dönüşmesi gereken bir sunucu
        hatasıdır. Yanlışlıkla 401 dönerse istemci oturumu kapatır ve kullanıcı
        hesabına erişemez.
        """
        if not token or not token.strip():
            raise InvalidTokenError("Oturum geçersiz.")

        client = await self.client()

        try:
            result = await client.auth.get_claims(token)
        except (AuthApiError, AuthInvalidJwtError) as e:
            debug_log("Token doğrulama hatası:", e)
            raise InvalidTokenError("Oturum geçersiz.")
        except Exception as e:
            debug_log("Token doğrulama hatası:", e)
            raise InvalidTokenError("Oturum geçersiz.")

        claims = _extract_claims(result)
        if not isinstance(claims, dict):
            raise InvalidTokenError("Oturum geçersiz.")

        subject = claims.get("sub")
        role = claims.get("role")
        if not subject:
            raise InvalidTokenError("Oturum geçersiz.")
        if role != _EXPECTED_ROLE:
            # Örn. yanlışlıkla istemciye sızan service_role anahtarı.
            debug_log("Token reddedildi — rol beklenenden farklı:", role)
            raise InvalidTokenError("Oturum geçersiz.")

        self._check_issuer(claims)

        return {
            "sub": str(subject),
            "email": claims.get("email"),
            "role": role,
            "source": _verification_source(token),
        }

    def _check_issuer(self, claims: Dict[str, Any]) -> None:
        """
        `iss` iddiasını denetler — ama YALNIZCA bildirim olarak.

        İmza zaten bu projenin JWKS anahtarlarıyla doğrulanmıştır; dolayısıyla
        `iss` uyuşmazlığı saldırı değil, yapılandırma farkıdır (örneğin özel
        alan adı). Bu yüzden reddedilmez, yalnızca `DEBUG=1` iken loglanır.
        """
        if not self.url:
            return
        expected = f"{self.url.rstrip('/')}/auth/v1"
        actual = claims.get("iss")
        if actual and actual != expected:
            debug_log("Token `iss` uyuşmuyor:", f"{actual} != {expected}")


def _extract_claims(result: Any) -> Optional[Dict[str, Any]]:
    """
    `get_claims()` sonucundan iddiaları sözlük olarak çıkarır.

    SDK'nin `ClaimsResponse` tipi bir **TypedDict**'tir; çalışma zamanında düz
    `dict` döner. Yalnızca `getattr(...).claims` ile okumak bu yüzden sessizce
    `None` üretir ve her geçerli token reddedilir. İki biçimi de kabul ediyoruz
    ki SDK tipi ileride nesneye dönerse kırılmasın.
    """
    if isinstance(result, dict):
        claims = result.get("claims")
    else:
        claims = getattr(result, "claims", None)
    return claims if isinstance(claims, dict) else None


def _token_header(token: str) -> Dict[str, Any]:
    """
    Token başlığını okur (base64url) — **DOĞRULAMA YAPMAZ**.

    Yalnızca hangi doğrulama yolunun izlendiğini (`jwks` / `gotrue`) bildirmek
    ve tanılama için kullanılır. İçeriğe güvenilmez; imza zaten `get_claims`
    tarafından denetlenmiştir.
    """
    try:
        raw = token.split(".", 1)[0]
        raw += "=" * (-len(raw) % 4)
        return json.loads(base64.urlsafe_b64decode(raw))
    except (ValueError, binascii.Error, IndexError):
        return {}


def _verification_source(token: str) -> str:
    """
    `get_claims`ın izlediği yolu tahmin eder (yalnızca log/tanı amaçlı).

    Simetrik token'larda açık anahtar JWKS'te olmadığı için doğrulama Auth
    sunucusunda yapılır; asimetrik olanlarda JWKS üzerinden yerelde yapılır.
    """
    header = _token_header(token)
    if header.get("alg") == _SYMMETRIC_ALG or not header.get("kid"):
        return "gotrue"
    return "jwks"


# ── Dönüşüm yardımcıları ─────────────────────────────────────────────────────


def _session_payload(response: Any) -> Dict[str, Any]:
    """GoTrue AuthResponse nesnesini API sözleşmesine çevirir."""
    session = getattr(response, "session", None)
    if session is None:
        raise AuthApiError(
            "Oturum oluşturulamadı. E-posta doğrulaması açıksa "
            "Supabase Dashboard'dan kapatın.",
            400,
            "session_missing",
        )

    return {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "token_type": session.token_type or "bearer",
        "expires_in": int(session.expires_in or 3600),
        "user": _user_to_dict(getattr(response, "user", None)),
    }


def _user_to_dict(user: Any) -> Dict[str, Any]:
    """GoTrue kullanıcı nesnesini düz sözlüğe çevirir."""
    if user is None:
        return {}
    metadata = getattr(user, "user_metadata", None) or {}
    return {
        "id": str(getattr(user, "id", "")),
        "email": getattr(user, "email", None),
        "username": metadata.get("username"),
        "display_name": metadata.get("display_name"),
        "avatar_url": metadata.get("avatar_url"),
        "created_at": _iso(getattr(user, "created_at", None)),
    }


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else str(value)


def _tr_message(error: AuthApiError) -> str:
    """
    GoTrue hata kodunu Türkçe API mesajına çevirir.

    Frontend `body.detail` alanını doğrudan kullanıcıya gösterir.
    """
    code = getattr(error, "code", None)
    message = AUTH_ERROR_MESSAGES.get(code or "")
    if message:
        return message
    return "Kimlik doğrulama işlemi başarısız oldu."


# Kimlik bilgisi hataları: 400 döner. 401 istemcide "oturum geçersiz" anlamına
# gelir ve yanlış parolada kullanıcıyı oturumu kapatmaya iter.
_CREDENTIAL_ERROR_CODES = ("invalid_credentials", "email_not_confirmed")

# GoTrue hata kodları → Türkçe API mesajları.
#
# Frontend `body.detail` alanını doğrudan kullanıcıya gösterdiği için bu eşleme
# tek kaynaktan yönetilir: hem bu modül (GoTrue sarmalayıcısı) hem de
# `api/routes/auth.py` aynı sözlüğü kullanır.
AUTH_ERROR_MESSAGES = {    "email_exists": "Bu e-posta adresi zaten kayıtlı.",
    "email_address_not_authorized": "Bu e-posta adresi için yeni kayıt kapalı.",
    "email_conflict_identity_not_deletable": "Bu e-posta adresi zaten kayıtlı.",
    "user_already_exists": "Bu e-posta adresi zaten kayıtlı.",
    "invalid_credentials": "E-posta veya parola hatalı.",
    "email_not_confirmed": "E-posta adresi henüz doğrulanmamış.",
    "signup_disabled": "Yeni kayıtlar şu anda kapalı.",
    "validation_failed": "Girilen bilgiler geçersiz.",
    "weak_password": "Parola çok zayıf.",
    "over_request_rate_limit": "Çok fazla istek gönderildi. Biraz bekleyip tekrar deneyin.",
    "over_email_send_rate_limit": "Çok fazla e-posta gönderildi. Biraz bekleyip tekrar deneyin.",
    "bad_json": "İstek gövdesi okunamadı.",
    "session_not_found": "Oturumun süresi doldu. Lütfen tekrar giriş yap.",
    "refresh_token_not_found": "Oturumun süresi doldu. Lütfen tekrar giriş yap.",
    "refresh_token_already_used": "Oturumun süresi doldu. Lütfen tekrar giriş yap.",
    "user_not_found": "Kullanıcı bulunamadı.",
    "no_authorization": "Oturum geçersiz.",
}

__all__ = [
    "AUTH_ERROR_MESSAGES",
    "AuthConfigurationError",
    "InvalidTokenError",
    "SupabaseAuthManager",
    "resolve_supabase_url",
    "resolve_anon_key",
    "resolve_service_role_key",
]
