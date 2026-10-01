"""
Extractor (çıkarıcı) ile ilgili API endpoint'leri.

Endpoint'ler:
  GET  /api/extractors                       → Yüklü tüm extractor'ları listele
  GET  /api/extract?url=...                  → URL'den medya çıkar (GET)
  POST /api/extract                          → URL'den medya çıkar (POST)
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.deps import get_extractor_manager, get_plugin_manager

# Doğrudan oynatılabilen medya uzantıları (Sinewix gibi JSON eklentiler .mkv döndürür).
_DOGRUDAN_MEDYA_RE = re.compile(
    r"\.(mkv|mp4|m3u8|webm|avi|m4v|mov|ts|flv|mpd)(\?|#|$)", re.IGNORECASE
)
from Core.Extractor.ExtractorModels import ExtractResult

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


async def _process_extract(url: str, referer: str | None = None) -> list[dict[str, Any]]:
    """
    Verilen URL'yi çözümler:
    1. Doğrudan medya dosyası (.mkv/.mp4/...) ise kendisi oynatılır.
    2. Doğrudan bir extractor URL'si ise ilgili extractor ile çözer.
    3. Bir plugin (film/dizi içerik sayfası) linki ise, eklentinin tüm izleme linklerini
       otomatik toplayıp her birini ilgili extractor ile paralel olarak çözer.
    """
    clean_url = (url or "").strip()
    if not clean_url:
        raise HTTPException(status_code=400, detail="URL boş olamaz.")

    # 1. URL doğrudan medya dosyası mı? (Sinewix .mkv vb.) -> extractor gerekmez.
    if _DOGRUDAN_MEDYA_RE.search(clean_url):
        return [{
            "extractor": "Direct",
            "result": {
                "name": "Direct Link",
                "url": clean_url,
                "referer": referer or clean_url,
                "headers": ({"Referer": referer} if referer else {}),
                "subtitles": [],
            },
        }]

    em = get_extractor_manager()
    pm = get_plugin_manager()

    # 2. URL doğrudan bilinen bir extractor URL'si mi? (Rapidrame, Close, Vidmoly vb.)
    direct_extractor = em.find_extractor(clean_url)
    if direct_extractor:
        try:
            result = await direct_extractor.extract(clean_url, referer=referer)
            return [{
                "extractor": direct_extractor.name,
                "result": _serialize(result),
            }]
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Medya çıkarılırken hata: {e}")

    # 3. URL bir eklentiye ait içerik (film/dizi) sayfası mı?
    plugin = pm.find_plugin_by_url(clean_url)
    if plugin:
        try:
            raw_links = await plugin.load_links(clean_url)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Eklenti bağlantıları alınırken hata: {e}")

        if not raw_links:
            return []

        async def _resolve_single_link(raw_item: Any) -> dict[str, Any] | None:
            # Durum A: Plugin zaten ExtractResult nesnesi döndürmüşse (örn. DiziBox)
            if isinstance(raw_item, ExtractResult):
                if not raw_item.url or not isinstance(raw_item.url, str) or not raw_item.url.startswith("http"):
                    return None

                # Embed URL mi yoksa direkt stream mi kontrol et
                sub_extractor = em.find_extractor(raw_item.url)
                if sub_extractor:
                    # Embed URL → extractor'a gönder
                    try:
                        sub_result = await sub_extractor.extract(raw_item.url, referer=raw_item.referer or clean_url)
                        # Plugin'den gelen headers ve referer'ı koru (extractor override etmiş olabilir)
                        if raw_item.headers:
                            sub_result.headers = {**sub_result.headers, **raw_item.headers}
                        if raw_item.referer:
                            sub_result.referer = raw_item.referer
                        return {
                            "extractor": sub_extractor.name,
                            "result": _serialize(sub_result),
                        }
                    except Exception as e:
                        print(f"Extractor {sub_extractor.name} failed for {raw_item.url}: {e}")
                        return None
                else:
                    # Direkt stream URL → olduğu gibi döndür
                    return {
                        "extractor": raw_item.name or getattr(plugin, "name", "Plugin"),
                        "result": _serialize(raw_item),
                    }

            # Durum B: Plugin embed / oynatıcı linki (string) döndürmüşse (örn. HDFilmCehennemi)
            if isinstance(raw_item, str):
                if not raw_item or not raw_item.startswith("http"):
                    return None

                sub_extractor = em.find_extractor(raw_item)
                if sub_extractor:
                    try:
                        sub_result = await sub_extractor.extract(raw_item, referer=clean_url)
                        return {
                            "extractor": sub_extractor.name,
                            "result": _serialize(sub_result),
                        }
                    except Exception as e:
                        print(f"Extractor {sub_extractor.name} failed for {raw_item}: {e}")
                        return None
                else:
                    return {
                        "extractor": "Direct",
                        "result": {
                            "name": "Direct Link",
                            "url": raw_item,
                            "referer": clean_url,
                            "headers": {},
                            "subtitles": [],
                        },
                    }

            return None

        tasks = [_resolve_single_link(item) for item in raw_links]
        resolved = await asyncio.gather(*tasks, return_exceptions=True)
        valid_results = []
        for r in resolved:
            if isinstance(r, Exception):
                print(f"Task failed: {r}")
            elif r is not None:
                valid_results.append(r)

        if not valid_results:
            raise HTTPException(status_code=404, detail="İçerikten oynatılabilir medya bağlantısı çıkarılamadı.")

        return valid_results

    # 4. Ne extractor ne de plugin eşleştiyse
    raise HTTPException(
        status_code=404,
        detail=f"Bu URL için uygun bir eklenti veya extractor bulunamadı: {clean_url}",
    )


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


@router.get("/extract", summary="URL'den medya çıkar (GET)")
async def extract_media_get(
    url: str = Query(..., description="Medya veya içerik sayfası URL'si"),
    referer: str | None = Query(None, description="Opsiyonel Referer başlığı"),
):
    """
    Verilen URL için medyayı çıkarır.
    İçerik sayfası (film/dizi) linki verilirse, tüm alternatif video kaynaklarını
    otomatik bulup extractor'lardan geçirerek tek seferde döndürür.
    """
    return await _process_extract(url=url, referer=referer)


@router.post("/extract", summary="URL'den medya çıkar (POST)")
async def extract_media_post(request: ExtractRequest):
    """
    Verilen URL için medyayı çıkarır.
    İçerik sayfası (film/dizi) linki verilirse, tüm alternatif video kaynaklarını
    otomatik bulup extractor'lardan geçirerek tek seferde döndürür.
    """
    return await _process_extract(url=request.url, referer=request.referer)
