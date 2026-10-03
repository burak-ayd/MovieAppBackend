"""
Uygulama sürümü — TEK KAYNAK.

Buradaki `APP_VERSION` değeri şu yüzeylerde görünür:

  * `GET /`                → sağlık sayfası (`{"status":"ok","version":"1.2.0", ...}`)
  * `/openapi.json`, `/docs` → FastAPI `info.version`
  * Başlangıç logu         → konsol (`api/app.py`) ve supervisor durum dosyası
  * Container healthcheck  → `ops/healthcheck.py` çıktısı

Bu modül BİLEREK yalnızca stdlib kullanır ve hiçbir yan etki içermez.
`ops/supervisor.py` gibi hafif süreçler de onu ucuz biçimde import edebilsin
diye sürüm bilgisi `Core/` içine değil, proje köküne konur: `Core/__init__.py`
Supabase/TMDB/MediaHandler'ı içe aktardığı için oraya konulsaydı her supervisor
açılışı tüm ağır bağımlılıkları yüklerdi.

Dağıtımda kodu düzenlemeden farklı bir sürüm basmak için `APP_VERSION` ortam
değişkeni ayarlanabilir (örn. CI etiketinden gelen sürüm).
"""

from __future__ import annotations

import os

APP_NAME = "MovieApp API"

# SemVer: MAJOR.MINOR.PATCH
APP_VERSION = "1.3.0"


def resolve_version() -> str:
    """
    Çalışan sürümü döndürür.

    `APP_VERSION` ortam değişkeni boş değilse kod değerini geçersiz kılar
    (yayınlama anında sürüm damgası basmak için). Aksi halde dosyadaki
    `APP_VERSION` kullanılır.
    """
    return (os.getenv("APP_VERSION") or "").strip() or APP_VERSION


def version_banner() -> str:
    """Log satırları için `MovieApp API 1.2.0` biçiminde metin."""
    return f"{APP_NAME} {resolve_version()}"


def version_info() -> dict[str, str]:
    """Sağlık ucu ve teşhis çıktıları için sözlük biçimi."""
    return {"name": APP_NAME, "version": resolve_version()}