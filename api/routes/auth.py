"""
Kimlik doğrulama endpoint'leri.

Endpoint'ler:
  POST /api/auth/signup   → Kayıt ol (GoTrue) + profil satırı oluştur
  POST /api/auth/login    → Giriş yap
  POST /api/auth/refresh  → Refresh token ile yeni access token
  POST /api/auth/logout   → GoTrue oturumunu kapat (refresh token iptali)
  GET  /api/auth/me       → Profil + bağlı cihaz listesi

Notlar:
  * Supabase Auth "Confirm email" KAPALI olmalıdır (SYNC_AUTH_PLAN.md §4.3).
    Aksi halde oturum token'ı dönmez ve mobilde her cihazda e-posta tıklama
    zorunluluğu doğar; senkronizasyonun "tek ekran, tek düğme" vaadi bozulur.
  * `detail` alanı her zaman Türkçedir; frontend bu metni doğrudan gösterir.
  * `response_model` burada bilinçli bir konvansiyon istisnasıdır (§4.2):
    token gövdesi gizli kalmamalı, OpenAPI şeması belgelemelidir.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, status
from supabase_auth.errors import AuthApiError

from api.deps import (
    CurrentClaims,
    OptionalToken,
    get_auth_manager,
    get_supabase_async,
)
from Core.Libs.AuthModels import (
    AuthSessionResponse,
    AuthUser,
    LoginRequest,
    MeResponse,
    RefreshRequest,
    SignupRequest,
)
from Core.Libs.Supabase import SupabaseManager
from Core.Libs.SupabaseAuth import (
    AUTH_ERROR_MESSAGES,
    AuthConfigurationError,
)
from Core.Libs.SyncModels import DeviceSummary

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Yardımcılar ──────────────────────────────────────────────────────────────


def _config_error(error: AuthConfigurationError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"Kimlik doğrulama servisi yapılandırılmamış: {error}",
    )


# Kimlik bilgisi hataları: daima 400 döner. 401 istemcide "oturum süresi doldu"
# anlamına gelir (sessizce refresh → çıkış yap) ve yanlış parolada kullanıcıyı
# oturumdan koparırdı.
_CREDENTIAL_ERROR_CODES = frozenset({"invalid_credentials", "email_not_confirmed"})

# Yenileme hataları: hepsi oturumun sonu anlamına gelir.
_REFRESH_ERROR_MESSAGES = {
    "refresh_token_not_found": "Oturumun süresi doldu. Lütfen tekrar giriş yap.",
    "refresh_token_already_used": "Oturum yenilendi. Lütfen tekrar giriş yap.",
    "session_not_found": "Oturumun süresi doldu. Lütfen tekrar giriş yap.",
    "session_expired": "Oturumun süresi doldu. Lütfen tekrar giriş yap.",
    "user_not_found": "Kullanıcı bulunamadı.",
    "no_authorization": "Oturumun süresi doldu. Lütfen tekrar giriş yap.",
    # GoTrue bozuk bir refresh token'a `validation_failed` / `bad_json` dönebilir.
    # Bunlar da "yenilenemedi" demektir, "form hatası" değil.
    "validation_failed": "Oturumun süresi doldu. Lütfen tekrar giriş yap.",
    "bad_json": "Oturumun süresi doldu. Lütfen tekrar giriş yap.",
}


def _refresh_error(error: Exception) -> HTTPException:
    """
    Token yenileme hatası — daima 401.

    Yenileme başarısız olduğunda oturum kurtarılamaz: refresh token ya geçersiz
    ya da süresi dolmuştur. İstemci 401'e sessizce yeniden giriş dener, o da
    olmazsa oturumu kapatır — kullanıcıya tek yol kalır. 400 dönmek istemcide
    "form hatası" anlamına gelir ve kırık oturumda kullanıcıyı sonsuza kadar
    kilitler.
    """
    code = getattr(error, "code", None)
    message = (
        _REFRESH_ERROR_MESSAGES.get(code or "")
        or "Oturumun süresi doldu. Lütfen tekrar giriş yap."
    )
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail=message
    )


def _auth_error(error: Exception) -> HTTPException:
    """GoTrue / ağ hatasını anlaşılır bir Türkçe HTTP hatasına çevirir."""
    if isinstance(error, AuthApiError):
        code = getattr(error, "code", None)

        # Mesaj önce hata kodundan türetilir; kod tanınmıyorsa yalnızca o zaman
        # kütüphanenin mesajına düşülür. Böylece kullanıcı İngilizce GoTrue metni
        # görmez.
        message = AUTH_ERROR_MESSAGES.get(code or "") or (
            str(error.args[0]) if error.args else "Kimlik doğrulama işlemi başarısız oldu."
        )

        # Kullanıcı adı benzersizlik çakışması.
        if code in ("username_exists", "user_already_exists") or (
            getattr(error, "status", None) == 409 and code
        ):
            return HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Bu kullanıcı adı alınmış.",
            )

        # GoTrue'nin durum kodu sürümden sürüme değişebiliyor; kimlik bilgisi
        # hataları burada sabitlenir (bkz. Core.Libs.SupabaseAuth.sign_in).
        http_status = (
            status.HTTP_400_BAD_REQUEST
            if code in _CREDENTIAL_ERROR_CODES
            else (getattr(error, "status", 400) or 400)
        )
        if not 400 <= http_status <= 599:
            http_status = status.HTTP_502_BAD_GATEWAY
        return HTTPException(status_code=http_status, detail=message)

    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Kimlik doğrulama servisine ulaşılamadı.",
    )


def _profile_to_user(
    user_id: str,
    email: Optional[str],
    profile: Optional[Dict[str, Any]],
) -> AuthUser:
    """`auth.users` kimliği ile `user_profiles` satırını tek modelde birleştirir."""
    profile = profile or {}
    birth_date = profile.get("birth_date")
    return AuthUser(
        id=user_id,
        email=email,
        username=profile.get("username"),
        display_name=profile.get("display_name"),
        avatar_url=profile.get("avatar_url"),
        bio=profile.get("bio"),
        language=profile.get("language") or "tr",
        is_private=bool(profile.get("is_private")),
        birth_date=str(birth_date) if birth_date else None,
        created_at=profile.get("created_at"),
        updated_at=profile.get("updated_at"),
    )


async def _user_view(
    db: SupabaseManager,
    user_id: str,
    email: Optional[str],
    with_devices: bool = False,
) -> Dict[str, Any]:
    """Profili (isteğe bağlı cihaz listesiyle) API sözlük biçimine çevirir."""
    profile = await db.get_profile(user_id)
    user = _profile_to_user(user_id, email, profile)

    devices: list[Dict[str, Any]] = []
    if with_devices:
        devices = [
            DeviceSummary(**row).model_dump() for row in await db.list_devices(user_id)
        ]

    return {"user": user.model_dump(), "devices": devices}


# ── Endpoint'ler ─────────────────────────────────────────────────────────────


@router.post("/signup", summary="Yeni hesap oluştur", response_model=AuthSessionResponse)
async def signup(payload: SignupRequest):
    """
    Yeni kullanıcı kaydeder ve oturum token'larını döner (`200`).

    `user_profiles.username` UNIQUE olduğu için kullanıcı adı çakışması
    409 ile bildirilir; e-posta çakışması GoTrue'dan 400 gelir.
    """
    db = get_supabase_async()

    if await db.username_taken(payload.username):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bu kullanıcı adı alınmış.",
        )

    auth = get_auth_manager()
    try:
        session = await auth.sign_up(
            email=payload.email,
            password=payload.password,
            username=payload.username,
            display_name=payload.display_name,
        )
    except AuthConfigurationError as e:
        raise _config_error(e)
    except Exception as e:
        raise _auth_error(e)

    user = session.get("user") or {}
    user_id = user.get("id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Kullanıcı oluşturulamadı.",
        )

    await db.create_profile(
        user_id=user_id,
        username=payload.username,
        display_name=payload.display_name,
    )

    session["user"] = (
        await _user_view(db, user_id, user.get("email") or payload.email)
    )["user"]
    return session


@router.post("/login", summary="Giriş yap", response_model=AuthSessionResponse)
async def login(payload: LoginRequest):
    """E-posta ve parola ile oturum açar."""
    db = get_supabase_async()

    try:
        session = await get_auth_manager().sign_in(payload.email, payload.password)
    except AuthConfigurationError as e:
        raise _config_error(e)
    except Exception as e:
        raise _auth_error(e)

    user = session.get("user") or {}
    user_id = user.get("id")
    if user_id:
        session["user"] = (await _user_view(db, user_id, user.get("email")))["user"]
    return session


@router.post("/refresh", summary="Erişim token'ını yenile", response_model=AuthSessionResponse)
async def refresh(payload: RefreshRequest):
    """
    Refresh token ile yeni bir erişim token'ı üretir.

    Frontend 401 aldığında bu ucu çağırır; başarısız olursa oturumu kapatır.
    """
    db = get_supabase_async()

    try:
        session = await get_auth_manager().refresh(payload.refresh_token)
    except AuthConfigurationError as e:
        raise _config_error(e)
    except Exception as e:
        raise _refresh_error(e)

    user = session.get("user") or {}
    user_id = user.get("id")
    if user_id:
        session["user"] = (await _user_view(db, user_id, user.get("email")))["user"]
    return session


@router.post("/logout", summary="Çıkış yap", status_code=status.HTTP_204_NO_CONTENT)
async def logout(token: OptionalToken):
    """
    GoTrue oturumunu kapatır (refresh token iptal edilir).

    Token yoksa veya geçersizse de 204 döner: frontend token'ları her hâlükârda
    yerel olarak siler ve "çıkış" kullanıcı açısından gerçekleşmiştir.
    """
    if token:
        await get_auth_manager().logout(token)
    return None


@router.get("/me", summary="Oturum ve profil bilgisi", response_model=MeResponse)
async def me(claims: CurrentClaims):
    """
    Doğrulanmış kullanıcının profilini ve bağlı cihaz listesini döner.

    E-posta JWT iddialarından gelir (`auth.users`), kullanıcı adı ve profil
    alanları `user_profiles` tablosundan okunur.
    """
    db = get_supabase_async()
    return await _user_view(db, str(claims["sub"]), claims.get("email"), with_devices=True)


__all__ = ["router"]
