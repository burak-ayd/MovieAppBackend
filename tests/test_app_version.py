"""
Sürüm bilgisi testleri.

`app_version.py` TEK KAYNAK olduğu için şu yüzeylerin hepsi aynı değeri
göstermeli: FastAPI `info.version`, sağlık ucu (`GET /`) ve OpenAPI şeması.
Ayrıca `APP_VERSION` ortam değişkeni ile geçersiz kılma çalışmalı.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app_version  # noqa: E402


def test_surum_bicimi_semver():
    """`MAJOR.MINOR.PATCH` — üç sayısal bileşen."""
    parcalar = app_version.APP_VERSION.split(".")
    assert len(parcalar) == 3, app_version.APP_VERSION
    assert all(b.isdigit() for b in parcalar), app_version.APP_VERSION


def test_env_tanimli_degilken_kod_degerini_kullanir(monkeypatch):
    monkeypatch.delenv("APP_VERSION", raising=False)
    assert app_version.resolve_version() == app_version.APP_VERSION


def test_env_surumu_gecersiz_kilar(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "9.9.9")
    assert app_version.resolve_version() == "9.9.9"


def test_env_bos_veya_bosluk_ise_kod_degeri(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "   ")
    assert app_version.resolve_version() == app_version.APP_VERSION


def test_banner_ve_info_ayni_surumu_tasir(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "3.1.4")
    assert app_version.version_banner() == f"{app_version.APP_NAME} 3.1.4"
    assert app_version.version_info() == {"name": app_version.APP_NAME, "version": "3.1.4"}


def test_modul_hafif_egilmis_olmalı():
    """
    `ops/supervisor.py` bu modülü import ediyor; ağır bağımlılık (Core paketi,
    Supabase, rich) buraya SIZDIRILMAMALI.
    """
    kaynak = Path(app_version.__file__).read_text(encoding="utf-8")
    for yasak in ("import requests", "import httpx", "from Core", "import rich", "import supabase"):
        assert yasak not in kaynak, f"app_version.py ağır bağımlılık içeriyor: {yasak}"


# ── Entegrasyon: uygulamanın yüzeyleri tek kaynağı kullanıyor mu? ────────────

@pytest.fixture(scope="module")
def api_app():
    pytest.importorskip("fastapi")
    from api.app import app as fastapi_app
    return fastapi_app


def test_fastapi_info_surumu_tek_kaynakla_ayni(api_app):
    assert api_app.version == app_version.resolve_version()


async def test_saglik_ucu_surumu_dondurur(api_app):
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=api_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yanit = await client.get("/")

    assert yanit.status_code == 200
    govde = yanit.json()
    assert govde["status"] == "ok"
    assert govde["version"] == app_version.resolve_version()


async def test_openapi_surumu_tek_kaynakla_ayni(api_app):
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=api_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yanit = await client.get("/openapi.json")

    assert yanit.status_code == 200
    assert yanit.json()["info"]["version"] == app_version.resolve_version()
