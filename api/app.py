"""
MovieApp API — FastAPI uygulaması.

Test dosyalarında (HDFilmcehennemiTest, DiziboxTest) yapılan tüm işlemleri
REST API endpoint'leri üzerinden sunmak için oluşturulmuştur.

Çalıştırma:
    uvicorn api.app:app --reload --host 0.0.0.0 --port 8000

Dokümantasyon:
    Swagger UI  → http://localhost:8000/docs
    ReDoc       → http://localhost:8000/redoc
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.deps import get_plugin_manager
from api.routes import plugins_router, extractors_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Uygulama yaşam döngüsü: başlatma ve kapatma işlemleri."""
    # ── Startup ──
    pm = get_plugin_manager()          # Eklentileri önceden yükle
    yield
    # ── Shutdown ──
    await pm.close_plugins()           # HTTP oturumlarını temizle


app = FastAPI(
    title="MovieApp API",
    description=(
        "Film ve dizi eklentilerini yöneten, arama yapan, "
        "içerik detaylarını getiren ve izleme bağlantılarını çıkaran REST API."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Router'ları kaydet ───────────────────────────────────────────────────────
app.include_router(plugins_router)
app.include_router(extractors_router)


# ── Kök endpoint ─────────────────────────────────────────────────────────────
@app.get("/", tags=["root"], summary="API durumu")
async def root():
    """API'nin çalıştığını doğrulamak için basit bir sağlık kontrolü."""
    return {
        "status": "ok",
        "message": "MovieApp API çalışıyor",
        "docs": "/docs",
    }




from fastapi.responses import Response
import cloudscraper

image_scraper = cloudscraper.create_scraper()

@app.api_route("/api/proxy/image", methods=["GET", "HEAD"], tags=["proxy"], summary="Resim proxy")
async def proxy_image(url: str):
    """Cloudflare veya anti-bot korumalı görselleri istemciye güvenle aktaran proxy."""
    try:
        headers = {
            "Referer": "https://www.hdfilmcehennemi.nl/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        }
        r = image_scraper.get(url, headers=headers, timeout=10)
        content_type = r.headers.get("content-type", "image/webp")
        return Response(
            content=r.content,
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=86400, s-maxage=86400"}
        )
    except Exception as e:
        return Response(status_code=500, content=str(e))
