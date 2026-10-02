"""
MovieApp API — FastAPI uygulaması.

Test dosyalarında (HDFilmcehennemiTest, DiziboxTest) yapılan tüm işlemleri
REST API endpoint'leri üzerinden sunmak için oluşturulmuştur.

Ayrıca cihazlar arası senkronizasyon ve kullanıcı hesabı uçlarını barındırır
(/api/auth/*, /api/sync/*). Plan: SYNC_AUTH_PLAN.md.

Çalıştırma:
    uvicorn api.app:app --reload --host 0.0.0.0 --port 8000

Üretim adresi:
    https://movieapi.burakaydogan.net.tr

Dokümantasyon (üretim):
    Swagger UI  → https://movieapi.burakaydogan.net.tr/docs
    ReDoc       → https://movieapi.burakaydogan.net.tr/redoc

Uçlar kendi `/api` önekini taşır. Taban URL'in sonuna `/api` YAZILMAZ:
`https://movieapi.burakaydogan.net.tr/api/plugins`  ✅
`https://movieapi.burakaydogan.net.tr/api/api/plugins`  ❌ (404)
"""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

# ── Windows import kilidi ────────────────────────────────────────────────────
# PLAN.md §2: Core.* mutlak import'ları için proje kökü yol üzerinde olmalıdır.
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# 🔴 KRİTİK: .env yalnızca burada okunur. Bu çağrı olmadan SUPABASE_URL boş
# döner ve tüm Supabase işlemleri (crawler + senkronizasyon) sessizce bozulur.
load_dotenv(ROOT_DIR / ".env")

from fastapi import FastAPI, Request, status  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from starlette.exceptions import HTTPException as StarletteHTTPException  # noqa: E402

from api.deps import (  # noqa: E402
    HTTP_413_TOO_LARGE,
    HTTP_422_INVALID_BODY,
    get_auth_manager,
    get_plugin_manager,
    get_supabase_async,
)
from api.routes import (  # noqa: E402
    auth_router,
    extractors_router,
    plugins_router,
    sync_router,
)
from Core.Helpers.Cli import debug_log, konsol  # noqa: E402
from Core.Libs.Supabase import (  # noqa: E402
    PushTooLargeError,
    SupabaseConfigurationError,
)
from Core.Libs.SupabaseAuth import (  # noqa: E402
    AuthConfigurationError,
    resolve_anon_key,
    resolve_service_role_key,
    resolve_supabase_url,
)


# ── Yapılandırma ─────────────────────────────────────────────────────────────

# İstemcilere gösterilen HERKESE AÇIK taban adresi.
#
# Yalnızca teşhis mesajlarında kullanılır (örn. istemci taban URL'in sonuna
# yanlışlıkla /api eklediğinde ne yapması gerektiğini söyleyen 404 mesajı).
# Sunucu hiçbir yerde bu adrese istek atmaz — dahili servisler `API_INTERNAL_URL`
# veya `http://api:8000` üzerinden konuşur.
#
# Alan adı değişirse tek yerden güncellenebilsin diye ortam değişkeniyle
# ezilebilir. Değiştirmek zorunda değilseniz bu sabit yeterlidir.
PUBLIC_API_URL = (os.getenv("PUBLIC_API_URL") or "https://movieapi.burakaydogan.net.tr").rstrip("/")


# CORS yalnızca web istemcisi içindir; React Native CORS motoru çalıştırmaz.
# Bearer token kullanıldığı için `allow_credentials` kapalıdır: wildcard origin
# ile credential birleşimi güvenlik açığıdır.
def parse_cors_origins(raw: str) -> list[str]:
    """
    `CORS_ORIGINS` değerini izinli origin listesine çevirir.

    Virgülle ayrılmış, boşlukları temizlenmiş girdiler. Boş veya tanımsız ise
    boş liste döner — CORS middleware hiç eklenmez (kapalı varsayılan).
    """
    return [origin.strip() for origin in (raw or "").split(",") if origin.strip()]


ALLOWED_ORIGINS = parse_cors_origins(os.getenv("CORS_ORIGINS") or "")


def configure_cors(application: FastAPI, origins: list[str]) -> None:
    """
    CORS middleware'ini ekler.

    İzinli origin listesi boşsa hiçbir şey eklenmez — CORS kapalıdır. Bu
    güvenli varsayılandır: `allow_origins=["*"]` + `allow_credentials=True`
    kombinasyonu güvenlik açığıdır ve React Native'de gereksizdir.
    """
    if not origins:
        return
    application.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,   # Bearer token taşınır; cookie yok
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Device-Id"],
    )


def _validate_config() -> None:
    """
    Başlangıçta yapılandırma bütünlüğünü denetler.

    Supabase eksikse API çalışmaya devam eder (plugin uçları Supabase'a ihtiyaç
    duymaz) ama sorun başlangıçta gürültülü bir uyarı olarak bildirilir.

    Not: Erişim token'larının doğrulanması için hiçbir anahtar gerekmez —
    SDK'nın `get_claims()` metodu JWKS ya da Auth sunucusu yolunu kendisi seçer.
    """
    if not resolve_supabase_url():
        konsol.log(
            "[bold yellow][UYARI][/] SUPABASE_URL tanımlı değil - "
            "giriş/kayıt ve senkronizasyon uçları çalışmayacak."
        )
        return

    if not resolve_anon_key():
        konsol.log(
            "[bold yellow][UYARI][/] SUPABASE_ANON_KEY tanımlı değil - "
            "giriş/kayıt çalışmayacak."
        )

    if not resolve_service_role_key()[0]:
        konsol.log(
            "[bold red][HATA][/] SUPABASE_SERVICE_ROLE_KEY tanımlı değil - "
            "RLS açık tablolara yazılamaz, senkronizasyon sessizce hiçbir şey taşımaz."
        )

    debug_log("CORS izinli origin'ler:", ALLOWED_ORIGINS or "(tanımlı değil)")


async def _report_verification_mode() -> None:
    """
    Başlangıçta token doğrulama modelini bildirir.

    JWKS uç noktası yalnızca asimetrik anahtarları yayımladığı için yanıt doluysa
    doğrulama tamamen yerel (ağ turu yok), boşsa simetrik (her istekte Auth
    sunucusuna gidiş) modundayız demektir. Tanı amaçlıdır — hata durumunda
    sessizce geçilir, başlangıç engellenmez.
    """
    if not resolve_supabase_url():
        return

    try:
        probe = await get_auth_manager().probe_verification_mode()
    except Exception as e:
        debug_log("JWT modeli tespiti başarısız:", e)
        return

    mode = probe.get("mode")
    if mode == "asymmetric":
        konsol.log(
            f"[bold green]JWT[/] Doğrulama asimetrik — JWKS'te "
            f"{probe['key_count']} anahtar ({', '.join(probe['algorithms'])}). "
            "İmzalar yerel doğrulanıyor, ağ turu yok."
        )
    elif mode == "symmetric":
        konsol.log(
            "[bold yellow][JWT][/] Doğrulama simetrik (HS256) — her korumalı istekte "
            "Auth sunucusuna gidiliyor (~20-40 ms). Dashboard → Authentication → "
            "JWT Signing Keys bölümünden asimetrik bir anahtara geçerseniz ağ turu "
            "otomatik olarak kesilir; kod değişikliği gerekmez."
        )
    else:
        konsol.log(
            "[bold yellow][UYARI][/] JWT doğrulama modeli belirlenemedi: "
            f"{probe.get('reason')}"
        )


# ── Yaşam döngüsü ────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Uygulama yaşam döngüsü: başlatma ve kapatma işlemleri."""
    # ── Startup ──
    _validate_config()
    await _report_verification_mode()
    pm = get_plugin_manager()          # Eklentileri önceden yükle
    yield
    # ── Shutdown ──
    await pm.close_plugins()           # HTTP oturumlarını temizle
    await get_supabase_async().close_async()   # PostgREST bağlantılarını kapat
    await get_auth_manager().close()           # GoTrue bağlantılarını kapat


app = FastAPI(
    title="MovieApp API",
    description=(
        "Film ve dizi eklentilerini yöneten, arama yapan, "
        "içerik detaylarını getiren ve izleme bağlantılarını çıkaran REST API. "
        "Ayrıca kullanıcı hesabı ve cihazlar arası senkronizasyon uçları."
    ),
    version="1.1.0",
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────────────────────────────────
configure_cors(app, ALLOWED_ORIGINS)


# ── Hata işleyiciler ─────────────────────────────────────────────────────────

@app.exception_handler(SupabaseConfigurationError)
async def _supabase_config_error(request: Request, exc: SupabaseConfigurationError):
    """Supabase bağlantı bilgileri eksikse 503 döner (500 değil)."""
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": f"Senkronizasyon servisi yapılandırılmamış: {exc}"},
    )


@app.exception_handler(AuthConfigurationError)
async def _auth_config_error(request: Request, exc: AuthConfigurationError):
    """GoTrue yapılandırması eksikse 503 döner."""
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": f"Kimlik doğrulama servisi yapılandırılmamış: {exc}"},
    )


@app.exception_handler(PushTooLargeError)
async def _push_too_large(request: Request, exc: PushTooLargeError):
    """
    Karar için okunan kayıtlar tavana dayandı → 413.

    Sessiz ezme yerine hata döner: istemci verisini küçültüp tekrar gönderir.
    """
    return JSONResponse(status_code=HTTP_413_TOO_LARGE, content={"detail": str(exc)})


# Pydantic hata tiplerinin Türkçe karşılıkları. Bilinmeyen tipler için ham
# mesaj kullanılır; alan adı (`loc`) aynen korunur.
_VALIDATION_MESSAGES = {
    "missing": "alan zorunlu",
    "string_too_short": "çok kısa",
    "string_too_long": "çok uzun",
    "int_parsing": "tam sayı olmalı",
    "int_type": "tam sayı olmalı",
    "float_parsing": "ondalık sayı olmalı",
    "float_type": "ondalık sayı olmalı",
    "bool_parsing": "true/false olmalı",
    "bool_type": "true/false olmalı",
    "list_type": "liste olmalı",
    "dict_type": "nesne olmalı",
    "model_type": "nesne olmalı",
    "literal_error": "geçersiz değer",
    "json_invalid": "geçersiz JSON",
    "value_error": "geçersiz değer",
    "greater_than_equal": "değer çok küçük",
    "less_than_equal": "değer çok büyük",
}


def _validation_message(error: dict) -> str:
    """Tek bir doğrulama hatasını okunabilir Türkçe metne çevirir."""
    error_type = str(error.get("type") or "")
    message = str(error.get("msg") or "Geçersiz değer").replace("Value error, ", "")

    # Kendi doğrulayıcılarımız zaten Türkçe mesaj üretir; onları olduğu gibi bırak.
    if error_type in ("value_error", "assertion_error"):
        return message

    return _VALIDATION_MESSAGES.get(error_type, message)


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    """
    Gövde/sorgu doğrulama hatalarını düz Türkçe `detail` metnine indirger.

    FastAPI varsayılanı `detail` alanını bir DİZİ döndürür. Mobil istemci
    `body.detail` değerini doğrudan `Error` mesajı olarak kullanır; dizi
    JavaScript'te "[object Object]" olarak görünür. Repo konvansiyonu gereği
    `detail` daima okunabilir bir Türkçe metin olmalıdır.
    """
    messages: list[str] = []
    for error in exc.errors():
        location = ".".join(
            str(part) for part in (error.get("loc") or ()) if part != "body"
        )
        text = _validation_message(error)
        messages.append(f"{location}: {text}" if location else text)

    detail = "Gönderilen bilgiler geçersiz."
    if messages:
        detail = "Gönderilen bilgiler geçersiz: " + "; ".join(messages)

    return JSONResponse(status_code=HTTP_422_INVALID_BODY, content={"detail": detail})


@app.exception_handler(StarletteHTTPException)
async def _http_exception(request: Request, exc: StarletteHTTPException):
    """
    HTTP hatalarını korur; yalnızca yapılandırma hatalarını teşhis eder.

    Varsayılan 404 gövdesi `{"detail": "Not Found"}` olup istemcide hiçbir ipucu
    vermez. En sık yaşanan hata taban URL'in sonuna `/api` yazılmasıdır: istek
    `/api/api/auth/signup` olur ve kullanıcı nedenini anlamaz. Bu durumda mesaj
    doğrudan ne yapılması gerektiğini söyler.
    """
    detail = exc.detail
    path = request.url.path

    for doubled in ("/api/api/", "/api/api"):
        if path.startswith(doubled):
            detail = (
                f"Yol bulunamadı: '{path}'. Taban URL'in sonuna '/api' yazılmış "
                "görünüyor ve istemci yolu ikinci kez ekliyor. "
                f"EXPO_PUBLIC_API_URL değeri '{PUBLIC_API_URL}' olmalı "
                "(sonunda /api olmadan)."
            )
            break

    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": detail},
        headers=getattr(exc, "headers", None),
    )


# ── Router'ları kaydet ───────────────────────────────────────────────────────
app.include_router(plugins_router)
app.include_router(extractors_router)
app.include_router(auth_router)
app.include_router(sync_router)


# ── Kök endpoint ─────────────────────────────────────────────────────────────
@app.get("/", tags=["root"], summary="API durumu")
async def root():
    """API'nin çalıştığını doğrulamak için basit bir sağlık kontrolü."""
    return {
        "status": "ok",
        "message": "MovieApp API çalışıyor",
        "docs": "/docs",
    }
