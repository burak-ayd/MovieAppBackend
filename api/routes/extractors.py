"""
Extractor (çıkarıcı) ile ilgili API endpoint'leri.

Endpoint'ler:
  GET  /api/extractors                       → Yüklü tüm extractor'ları listele
  POST /api/extract                          → Bir URL'den medya çıkar
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.deps import get_extractor_manager

router = APIRouter(prefix="/api", tags=["extractors"])


class ExtractRequest(BaseModel):
    """Extract endpoint'i için istek modeli."""
    url: str
    referer: str | None = None


def _serialize(obj: Any) -> Any:
    """Pydantic model veya liste/dict'i JSON-uyumlu formata çevirir."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, list):
        return [_serialize(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    return obj


@router.get("/extractors", summary="Tüm extractor'ları listele")
async def list_extractors():
    """Yüklü tüm extractor'ların listesini döndürür."""
    em = get_extractor_manager()
    extractors = []
    for extractor_cls in em.extractors:
        ext = extractor_cls()
        extractors.append({
            "name": ext.name,
            "main_url": ext.main_url,
        })
    return {"extractors": extractors}


@router.post("/extract", summary="URL'den medya çıkar")
async def extract_media(request: ExtractRequest):
    """
    Verilen URL için uygun extractor'ı bulur ve medya bilgilerini çıkarır.
    Sonuçta doğrudan oynatılabilir URL, header ve altyazı bilgileri yer alır.
    """
    em = get_extractor_manager()
    extractor = em.find_extractor(request.url)

    if not extractor:
        raise HTTPException(
            status_code=404,
            detail=f"Bu URL için uygun bir extractor bulunamadı: {request.url}",
        )

    try:
        result = await extractor.extract(request.url, referer=request.referer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Medya çıkarılırken hata: {e}")

    return {
        "extractor": extractor.name,
        "result": _serialize(result),
    }
