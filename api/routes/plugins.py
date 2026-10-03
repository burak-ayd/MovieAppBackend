"""
Plugin (eklenti) ile ilgili API endpoint'leri.

Endpoint'ler:
  GET  /api/plugins                          → Tüm eklentileri listele
  GET  /api/plugins/random                   → Tüm eklentilerden rastgele içerikler
  GET  /api/plugins/{name}                   → Tek bir eklentinin detay bilgisi
  GET  /api/plugins/{name}/random            → Eklentiden rastgele içerikler
  GET  /api/plugins/{name}/main-page         → Eklentinin ana sayfa içerikleri
  GET  /api/plugins/{name}/categories        → Eklentinin mevcut kategorileri
  GET  /api/plugins/{name}/search?q=...      → Tek eklentide arama
  GET  /api/plugins/{name}/detail?url=...    → İçerik detayı (film / dizi)
  GET  /api/plugins/{name}/links?url=...     → İzleme bağlantıları
  GET  /api/search?q=...                     → Tüm eklentilerde arama
  GET  /api/random                           → Tüm eklentilerden rastgele içerikler
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from api.deps import get_plugin_manager, get_extractor_manager, get_tmdb_enricher
from Core.Plugin.PluginBase import PluginBase
from Core.Plugin.PluginModels import SeriesInfo

router = APIRouter(prefix="/api", tags=["plugins"])


# ── TMDB görsel zenginleştirme ────────────────────────────────────────────────
#
# Poster/arka plan/logo/oyuncu fotoğrafı gibi GÖRSEL alanlar TMDB'den alınır.
# Sıra: önce TMDB'ye istek → cevap varsa eklenti değerinin yerine yazılır.
# TMDB çökerse, rate limit'e takılırsa, anahtar yoksa veya eşleşme bulunamazsa
# zenginleştirme sessizce atlanır ve eklentinin kendi verisi aynen kalır.
#
# `try/except` burada savunma katmanıdır: zenginleştirme bir "bonus"tur ve
# hiçbir koşulda isteği düşürmemelidir.

async def _zenginlestir(oge: Any, detay: bool = False) -> Any:
    """Tek modeli TMDB görselleriyle zenginleştirir (hata halinde dokunmaz)."""
    enricher = get_tmdb_enricher()
    if not enricher.aktif:
        return oge
    try:
        return await enricher.zenginlestir(oge, detay=detay)
    except Exception:
        return oge


async def _zenginlestir_liste(ogeler: list[Any], detay: bool = False) -> list[Any]:
    """Liste sonucunu paralel zenginleştirir (hata halinde dokunmaz)."""
    enricher = get_tmdb_enricher()
    if not enricher.aktif or not ogeler:
        return ogeler
    try:
        return await enricher.zenginlestir_liste(ogeler, detay=detay)
    except Exception:
        return ogeler


# ── Yardımcı Fonksiyonlar ────────────────────────────────────────────────────


def _get_plugin(name: str) -> PluginBase:
    """İsme göre eklenti döndürür; bulunamazsa 404 fırlatır."""
    pm = get_plugin_manager()
    plugin = pm.select_plugin(name)
    if plugin is None:
        raise HTTPException(status_code=404, detail=f"'{name}' adında bir eklenti bulunamadı.")
    return plugin


def _plugin_info(plugin: PluginBase) -> dict[str, Any]:
    """Eklenti meta verilerini sözlük olarak döndürür."""
    return {
        "name": plugin.name,
        "language": plugin.language,
        "main_url": plugin.main_url,
        "description": plugin.description,
        "favicon": plugin.favicon,
        "categories": list(plugin.main_page.keys()) if plugin.main_page else [],
    }


def _serialize(obj: Any) -> Any:
    """Pydantic model veya liste/dict'i JSON-uyumlu formata çevirir."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, list):
        return [_serialize(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    return obj


# ── Endpoint'ler ──────────────────────────────────────────────────────────────


@router.get("/plugins", summary="Tüm eklentileri listele")
async def list_plugins():
    """Yüklü tüm eklentilerin listesini ve temel bilgilerini döndürür."""
    pm = get_plugin_manager()
    plugins = []
    for name in pm.get_plugin_names():
        plugin = pm.select_plugin(name)
        if plugin:
            plugins.append(_plugin_info(plugin))
    return {"plugins": plugins}


@router.get("/plugins/random", summary="Tüm eklentilerden rastgele içerikler")
@router.get("/random", summary="Tüm eklentilerden rastgele içerikler")
async def get_all_plugins_random(
    count_per_plugin: int = Query(3, ge=1, le=20, description="Her eklentiden alınacak rastgele içerik sayısı"),
):
    """
    Yüklü tüm eklentilerden 'count_per_plugin' (varsayılan 3) adet rastgele MainPageResult döner.
    """
    pm = get_plugin_manager()
    plugin_names = pm.get_plugin_names()

    async def _get_single(p_name: str):
        p = pm.select_plugin(p_name)
        if not p:
            return p_name, []
        with suppress(Exception):
            res = await p.get_random(count=count_per_plugin)
            res = await _zenginlestir_liste(res or [])
            return p_name, res or []
        return p_name, []

    tasks = [_get_single(name) for name in plugin_names]
    results_pairs = await asyncio.gather(*tasks)

    by_plugin = {}
    all_items = []
    for p_name, items in results_pairs:
        serialized = _serialize(items)
        by_plugin[p_name] = serialized
        all_items.extend(serialized)

    return {
        "count_per_plugin": count_per_plugin,
        "total": len(all_items),
        "plugins": by_plugin,
        "results": all_items,
    }


@router.get("/plugins/{name}/random", summary="Eklentiden rastgele içerikler")
async def get_plugin_random(
    name: str,
    count: int = Query(3, ge=1, le=50, description="Döndürülecek rastgele içerik sayısı"),
):
    """
    Belirtilen eklentiden rastgele 'count' (varsayılan 3) adet MainPageResult nesnesi döndürür.
    """
    plugin = _get_plugin(name)
    try:
        results = await plugin.get_random(count=count)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Rastgele içerik alınırken hata: {e}")

    results = await _zenginlestir_liste(results or [])
    return {
        "plugin": plugin.name,
        "count": len(results),
        "results": _serialize(results) if results else [],
    }


@router.get("/plugins/{name}", summary="Eklenti detayı")
async def get_plugin_detail(name: str):
    """Belirtilen eklentinin detay bilgisini döndürür."""
    plugin = _get_plugin(name)
    return _plugin_info(plugin)


@router.get("/plugins/{name}/categories", summary="Eklenti kategorileri")
async def get_plugin_categories(name: str):
    """Eklentinin desteklediği kategorileri listeler."""
    plugin = _get_plugin(name)
    categories = []
    if plugin.main_page:
        for category_name, url in plugin.main_page.items():
            categories.append({"name": category_name, "url": url})
    return {"plugin": plugin.name, "categories": categories}


@router.get("/plugins/{name}/main-page", summary="Ana sayfa içerikleri")
async def get_plugin_main_page(
    name: str,
    page: int = Query(1, ge=1, description="Sayfa numarası"),
    url: str = Query("", description="Belirli bir kategori URL'si (boş bırakılırsa varsayılan)"),
    category: str = Query("", description="Kategori adı"),
):
    """
    Eklentinin ana sayfa / kategori içeriklerini döndürür.
    """
    plugin = _get_plugin(name)
    try:
        results = await plugin.get_main_page(page=page, url=url, category=category)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ana sayfa yüklenirken hata: {e}")

    results = await _zenginlestir_liste(results or [])
    return {
        "plugin": plugin.name,
        "page": page,
        "category": category or None,
        "results": _serialize(results) if results else [],
    }


@router.get("/plugins/{name}/search", summary="Eklentide arama")
async def search_in_plugin(
    name: str,
    q: str = Query(..., min_length=1, description="Arama sorgusu"),
):
    """Belirtilen eklentide arama yapar."""
    plugin = _get_plugin(name)
    try:
        results = await plugin.search(q)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Arama sırasında hata: {e}")

    results = await _zenginlestir_liste(results or [])
    return {
        "plugin": plugin.name,
        "query": q,
        "results": _serialize(results) if results else [],
    }


@router.get("/plugins/{name}/detail", summary="İçerik detayı")
async def get_content_detail(
    name: str,
    url: str = Query(..., description="İçerik sayfasının URL'si"),
):
    """
    Bir film veya dizinin detay bilgilerini döndürür.
    (poster, açıklama, yıl, IMDB puanı, bölümler vs.)
    """
    plugin = _get_plugin(name)
    try:
        media_info = await plugin.load_item(url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Detay yüklenirken hata: {e}")

    if not media_info:
        raise HTTPException(status_code=404, detail="İçerik detayı bulunamadı.")

    # Detayda logo, arka plan ve oyuncu fotoğrafları da istenir.
    media_info = await _zenginlestir(media_info, detay=True)

    data = _serialize(media_info)
    data["is_series"] = isinstance(media_info, SeriesInfo)
    return {"plugin": plugin.name, "detail": data}


@router.get("/plugins/{name}/links", summary="İzleme bağlantıları")
async def get_watch_links(
    name: str,
    url: str = Query(..., description="İçerik sayfasının URL'si"),
):
    """
    Bir film/bölüm için mevcut izleme bağlantılarını döndürür.
    Her bağlantı, hangi extractor ile eşleştiği bilgisiyle birlikte sunulur.
    """
    plugin = _get_plugin(name)
    try:
        links = await plugin.load_links(url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bağlantılar yüklenirken hata: {e}")

    if not links:
        return {"plugin": plugin.name, "links": []}

    # Bağlantıları extractor'larla eşleştir
    em = get_extractor_manager()
    mapping = em.map_links_to_extractors(links)

    enriched_links = []
    for link in links:
        extractor = em.find_extractor(link)
        enriched_links.append({
            "url": link,
            "extractor": extractor.name if extractor else None,
            "label": mapping.get(link, None),
        })

    return {"plugin": plugin.name, "links": enriched_links}


@router.get("/search", summary="Tüm eklentilerde arama")
async def search_all_plugins(
    q: str = Query(..., min_length=1, description="Arama sorgusu"),
):
    """
    Tüm eklentilerde aynı anda arama yapar ve sonuçları birleştirir.
    Her sonuca hangi eklentiden geldiği bilgisi eklenir.
    """
    pm = get_plugin_manager()
    plugin_names = pm.get_plugin_names()

    async def _search_single(plugin_name: str):
        plugin = pm.select_plugin(plugin_name)
        if not plugin:
            return []
        with suppress(Exception):
            results = await plugin.search(q)
            if results:
                items = _serialize(await _zenginlestir_liste(results))
                for item in items:
                    item["plugin"] = plugin_name
                return items
        return []

    tasks = [_search_single(name) for name in plugin_names]
    all_results = await asyncio.gather(*tasks)

    merged = []
    for result_list in all_results:
        merged.extend(result_list)

    return {"query": q, "total": len(merged), "results": merged}
