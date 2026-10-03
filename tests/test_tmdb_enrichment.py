"""
TMDB görsel zenginleştirme testleri — tamamı ÇEVRİMİÇİ (ağ yok).

Kapsanan davranışlar:
  * TMDB cevabı varsa görseller eklenti değerinin YERİNE yazılır
  * TMDB çökerse / 429 / zaman aşımı / anahtar yoksa → eklenti verisi KORUNUR
  * Eşleştirme sırası: tmdb_id → imdb_id → isim+yıl
  * Önbellek: ikinci çağrıda HTTP isteği yapılmaz
  * Single-flight: eşzamanlı 10 çağrı TEK istek atar
  * Devre kesici: art arda hatalarda istekler durur
"""

import asyncio
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.Helpers.TMDBEnricher import TMDBEnricher  # noqa: E402
from Core.Libs.TMDB import TMDBClient, normalize_title, parse_year  # noqa: E402
from Core.Plugin.PluginModels import (  # noqa: E402
    MainPageResult,
    MovieInfo,
    SearchResult,
    SeriesInfo,
)


# ── Sahte TMDB sunucusu ──────────────────────────────────────────────────────

POSTER = "/poster.jpg"
BACKDROP = "/backdrop.jpg"


class FakeTMDB:
    """httpx MockTransport tabanlı sahte TMDB; istek sayacı tutar."""

    def __init__(self, davranis="normal"):
        self.davranis = davranis
        self.istekler: list[str] = []
        self.sorgular: list[str] = []      # search/multi'ye gönderilen ham sorgular

    def handler(self, request: httpx.Request) -> httpx.Response:
        # base_url "/3" ile bittiği için yol "/3/search/multi" gelir.
        yol = request.url.path
        if yol.startswith("/3"):
            yol = yol[2:]
        self.istekler.append(yol)

        if self.davranis == "asiri":
            raise httpx.ConnectTimeout("zaman aşımı")
        if self.davranis == "500":
            return httpx.Response(500, json={"status_message": "boom"})
        if self.davranis == "429":
            return httpx.Response(429, headers={"Retry-After": "1"}, json={})
        if self.davranis == "401":
            return httpx.Response(
                401, json={"status_message": "Invalid API key: You must be granted a valid key."}
            )

        if yol.startswith("/find/"):
            return httpx.Response(200, json={
                "movie_results": [{"id": 550, "title": "Fight Club",
                                   "poster_path": POSTER, "backdrop_path": BACKDROP,
                                   "release_date": "1999-10-15", "popularity": 60.0}],
                "tv_results": [],
            })

        if yol.startswith("/search/multi"):
            sorgu = dict(request.url.params)
            q = sorgu.get("query", "").lower()
            self.sorgular.append(q)
            # Canlı ölçüm: TMDB pazarlama kelimeli sorguya 0 sonuç veriyor
            # ("Esaretin Bedeli izle" → 0, "esaretin bedeli" → 1).
            if any(pazarlama in q for pazarlama in ("izle", "full film", "full türkçe")):
                return httpx.Response(200, json={"results": []})
            if "sezon" in q or "bölüm" in q or "bolum" in q or "season" in q:
                # Canlı davranış: bölüm ibareli sorgu eşleşmez.
                return httpx.Response(200, json={"results": []})
            if "matrix" in q:
                return httpx.Response(200, json={"results": [{
                    "id": 603, "media_type": "movie", "title": "The Matrix",
                    "original_title": "The Matrix", "poster_path": POSTER,
                    "backdrop_path": BACKDROP, "release_date": "1999-03-31",
                    "popularity": 80.0,
                }]})
            if "office" in q:
                return httpx.Response(200, json={"results": [{
                    "id": 2316, "media_type": "tv", "name": "The Office",
                    "original_name": "The Office", "poster_path": POSTER,
                    "backdrop_path": BACKDROP, "first_air_date": "2005-03-24",
                    "popularity": 50.0,
                }]})
            return httpx.Response(200, json={"results": []})

        if yol.startswith("/movie/") or yol.startswith("/tv/"):
            return httpx.Response(200, json={
                "id": int(yol.rsplit("/", 1)[-1]),
                "title": "The Matrix", "original_title": "The Matrix",
                "release_date": "1999-03-31", "popularity": 80.0,
                "poster_path": POSTER, "backdrop_path": BACKDROP,
                "imdb_id": "tt0133093",
                "external_ids": {"imdb_id": "tt0133093"},
                "images": {"logos": [{"iso_639_1": "en", "file_path": "/logo.png"}]},
                "credits": {"cast": [{"name": "Keanu Reeves", "profile_path": "/k.png"}]},
                "videos": {"results": [{"site": "YouTube", "key": "vKQi3bBA1y8"}]},
            })

        return httpx.Response(404, json={})

    def istemci(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler), timeout=2.0)


def istemci_uret(davranis="normal") -> tuple[TMDBClient, FakeTMDB]:
    sahte = FakeTMDB(davranis)
    tmdb = TMDBClient(api_key="test", timeout=2.0)
    tmdb._client = sahte.istemci()   # gerçek ağ kullanılmaz
    return tmdb, sahte


# ── Yardımcılar ──────────────────────────────────────────────────────────────

def test_normalizasyon():
    assert normalize_title("The Matrix (1999) izle") == "the matrix"
    assert normalize_title("  Şüpheli  ") == "şüpheli"
    assert normalize_title(None) == ""


@pytest.mark.parametrize(
    "ham, beklenen",
    [
        # DiziBox "Son Bölümler" kartlarındaki gerçek başlıklar
        ("War 1.Sezon 1.Bölüm", "war"),
        ("Zmora 1.Sezon 1.Bölüm", "zmora"),
        ("All Creatures Great and Small 7.Sezon 3.Bölüm", "all creatures great and small"),
        ("DARK MATTER (2024) 2.Sezon 6.Bölüm", "dark matter"),
        ("4 Blocks Zero 1.Sezon 2.Bölüm", "4 blocks zero"),
        ("Breaking Bad 1. Sezon 2. Bölüm", "breaking bad"),
        # Boşluklu/noktasız varyantlar
        ("Succesion sezon 3 bölüm 4", "succesion"),
        # İngilizce
        ("Succesion Season 3 Episode 4", "succesion"),
        ("The Office S02E05", "the office s02e05"),
    ],
)
def test_bolum_ibareleri_temizlenir(ham, beklenen):
    """
    Regresyon: bölüm ibareleri eşleştirmeyi bozuyordu.

    DiziBox'un "Son Bölümler"/"Popüler Diziler" kategorilerinde başlık
    "War 1.Sezon 1.Bölüm" biçiminde geliyor; bu ibareler temizlenmezse TMDB
    hiç eşleşmiyor.
    """
    assert normalize_title(ham) == beklenen


@pytest.mark.parametrize(
    "baslik",
    ["1917", "2012", "Blade Runner 2049", "9", "300"],
)
def test_yil_taşıyan_basliklar_bozulmaz(baslik):
    """Sadece "sezon/bölüm" ibareleri atılır; yıllar (1917, 2049) KALIR."""
    assert normalize_title(baslik) == baslik.lower()


def test_yil_ayristirma():
    assert parse_year("2026") == 2026
    assert parse_year("2020-2024") == 2020
    assert parse_year(1999) == 1999
    assert parse_year(None) is None
    assert parse_year("bilinmiyor") is None


# ── Fail-open: TMDB yokken eklenti verisi korunmalı ──────────────────────────

@pytest.mark.parametrize("davranis", ["asiri", "500", "429"])
async def test_tmdb_hatasi_verilerin_korunmasina_yol_acmaz(davranis):
    tmdb, _ = istemci_uret(davranis)
    enricher = TMDBEnricher(tmdb)

    ornek = MovieInfo(
        url="https://site.example/film",
        title="Matrix",
        poster_url="https://site.example/poster.jpg",
    )
    sonuc = await enricher.zenginlestir(ornek, detay=True)

    assert sonuc.poster_url == "https://site.example/poster.jpg", "TMDB hatasında plugin görseli korunmalı"
    await tmdb.aclose()


async def test_anahtar_yokken_hizli_ve_dokunulmaz():
    tmdb = TMDBClient(api_key="")
    enricher = TMDBEnricher(tmdb)
    assert enricher.aktif is False

    ornek = SearchResult(title="X", url="https://s.example/x", poster="https://s.example/p.jpg")
    sonuc = await enricher.zenginlestir(ornek)
    assert sonuc.poster == "https://s.example/p.jpg"
    assert tmdb.istatistik()["istek"] == 0, "anahtar yokken istek atılmamalı"


async def test_eslesme_bulunamazsa_plugin_gorseli_kalir():
    tmdb, _ = istemci_uret()
    enricher = TMDBEnricher(tmdb)

    ornek = MainPageResult(title="Hiç Yok Böyle Bir Film 9999", url="https://s/x",
                           poster="https://s/p.jpg")
    sonuc = await enricher.zenginlestir(ornek)
    assert sonuc.poster == "https://s/p.jpg"
    await tmdb.aclose()


# ── TMDB cevap verirse görseller eklenti değerinin yerine geçer ──────────────

async def test_tmdb_gorselleri_uygulanir():
    tmdb, _ = istemci_uret()
    enricher = TMDBEnricher(tmdb)

    ornek = MovieInfo(url="https://s/m", title="The Matrix",
                      poster_url="https://s/eski.jpg", backdrop_url=None)
    sonuc = await enricher.zenginlestir(ornek, detay=True)

    assert sonuc.poster_url == "https://image.tmdb.org/t/p/w500/poster.jpg"
    assert sonuc.backdrop_url == "https://image.tmdb.org/t/p/w1280/backdrop.jpg"
    assert sonuc.logo_url == "https://image.tmdb.org/t/p/w500/logo.png"
    assert sonuc.cast_images == {"Keanu Reeves": "https://image.tmdb.org/t/p/w185/k.png"}
    assert sonuc.imdb_id == "tt0133093"
    assert sonuc.tmdb_id == 603
    assert sonuc.fragman_url == "https://www.youtube.com/watch?v=vKQi3bBA1y8"
    await tmdb.aclose()


async def test_liste_gorselleri_orta_boyut_kullanir():
    """Liste kartlarında w500 değil w342 (hafif, görünür fark yok)."""
    tmdb, _ = istemci_uret()
    enricher = TMDBEnricher(tmdb)

    oge = MainPageResult(title="The Matrix", url="https://s/m", poster=None)
    sonuc = await enricher.zenginlestir(oge)

    assert sonuc.poster == "https://image.tmdb.org/t/p/w342/poster.jpg"
    assert sonuc.backdrop_url == "https://image.tmdb.org/t/p/w1280/backdrop.jpg"
    await tmdb.aclose()


async def test_tmdb_gorseli_plugin_gorselinin_yerine_gecer():
    """Kullanıcı kuralı: TMDB cevap verirse eklenti görseli DEĞİŞTİRİLİR."""
    tmdb, _ = istemci_uret()
    enricher = TMDBEnricher(tmdb)

    oge = SearchResult(title="The Matrix", url="https://s/m", poster="https://s/kendi.jpg")
    sonuc = await enricher.zenginlestir(oge)
    assert sonuc.poster == "https://image.tmdb.org/t/p/w342/poster.jpg"
    await tmdb.aclose()


async def test_tmdb_bos_donderse_plugin_gorseli_kalir():
    """TMDB görsel vermezse mevcut değer boşaltılmaz."""
    tmdb, _ = istemci_uret()
    enricher = TMDBEnricher(tmdb)

    dizi = SearchResult(title="Hiç Yok", url="https://s/x", poster="https://s/kendi.jpg")
    sonuc = await enricher.zenginlestir(dizi)
    assert sonuc.poster == "https://s/kendi.jpg"
    await tmdb.aclose()


async def test_gorsel_disinda_alanlar_korunur():
    """Fragman/kimlik gibi görsel olmayan alanlarda plugin kazanır."""
    tmdb, _ = istemci_uret()
    enricher = TMDBEnricher(tmdb)

    # Not: MovieInfo.fragman_url validator'ı YouTube kimliğine dönüştürür.
    ornek = MovieInfo(url="https://s/m", title="The Matrix", release_date="1999",
                      fragman_url="pluginTRAILER")
    sonuc = await enricher.zenginlestir(ornek, detay=True)

    assert sonuc.fragman_url.endswith("pluginTRAILER"), "plugin fragmanı korunmalı"
    assert "vKQi3bBA1y8" not in (sonuc.fragman_url or ""), "TMDB fragmanı eklentiyi ezmemeli"
    await tmdb.aclose()


async def test_dizi_modelinde_poster_alani_doldurulur():
    """Dizi (`content_type="series"`) araması TV sonucuyla eşleşmeli."""
    tmdb, _ = istemci_uret()
    enricher = TMDBEnricher(tmdb)

    dizi = SeriesInfo(url="https://s/d", title="The Office", content_type="series", poster=None)
    sonuc = await enricher.zenginlestir(dizi, detay=True)
    assert sonuc.poster == "https://image.tmdb.org/t/p/w500/poster.jpg"
    assert sonuc.tmdb_id == 2316
    await tmdb.aclose()


# ── Eşleştirme sırası ───────────────────────────────────────────────────────

async def test_tmdb_id_ile_dogrudan_gider_arama_yapmaz():
    tmdb, sahte = istemci_uret()
    enricher = TMDBEnricher(tmdb)

    oge = MovieInfo(url="https://s/m", title="Matrix", tmdb_id=603)
    await enricher.zenginlestir(oge, detay=True)

    assert any(p.startswith("/movie/603") for p in sahte.istekler)
    assert not any("search" in p for p in sahte.istekler), "tmdb_id varken arama yapılmamalı"
    await tmdb.aclose()


async def test_imdb_id_ile_find_kullanilir():
    tmdb, sahte = istemci_uret()
    enricher = TMDBEnricher(tmdb)

    oge = MovieInfo(url="https://s/m", title="Matrix", imdb_id="tt0133093")
    await enricher.zenginlestir(oge, detay=True)

    assert any(p.startswith("/find/tt0133093") for p in sahte.istekler)
    await tmdb.aclose()


async def test_kimlik_yoksa_isim_ve_yil_ile_arama():
    tmdb, sahte = istemci_uret()
    enricher = TMDBEnricher(tmdb)

    oge = MovieInfo(url="https://s/m", title="The Matrix", release_date="1999")
    sonuc = await enricher.zenginlestir(oge, detay=True)

    assert any("search/multi" in p for p in sahte.istekler)
    assert sonuc.poster_url and "@2x" not in sonuc.poster_url
    await tmdb.aclose()


async def test_yil_sapmasi_eslesmeyi_engeller():
    """Benzer başlıklı ama yılı tutmayan bir film kabul edilmemeli."""
    tmdb, _ = istemci_uret()
    enricher = TMDBEnricher(tmdb)

    # TMDB'de 1999; burada 2015 → 16 yıllık sapma eşiğin altına düşmeli.
    oge = MovieInfo(url="https://s/m", title="The Matrix", release_date="2015",
                    poster_url="https://s/kendi.jpg")
    sonuc = await enricher.zenginlestir(oge, detay=True)
    assert sonuc.poster_url == "https://s/kendi.jpg", "yıl sapması eşleşmemeli"
    await tmdb.aclose()


async def test_yil_bir_yil_farkla_tolere_edilir():
    """1 yıllık fark (gösterim/kitap yılı farkları) eşleşmeyi bozmamalı."""
    tmdb, _ = istemci_uret()
    enricher = TMDBEnricher(tmdb)

    oge = MovieInfo(url="https://s/m", title="The Matrix", release_date="1998")
    sonuc = await enricher.zenginlestir(oge, detay=True)
    assert sonuc.poster_url == "https://image.tmdb.org/t/p/w500/poster.jpg"
    await tmdb.aclose()


# ── Önbellek / single-flight / devre kesici ──────────────────────────────────

async def test_onbellek_ikinci_cagri_yeni_istek_yapmaz():
    tmdb, sahte = istemci_uret()
    enricher = TMDBEnricher(tmdb)

    oge = MovieInfo(url="https://s/m", title="The Matrix", release_date="1999")
    await enricher.zenginlestir(oge, detay=True)
    ilk = len(sahte.istekler)
    await enricher.zenginlestir(MovieInfo(url="https://s/m2", title="The Matrix",
                                          release_date="1999"), detay=True)

    assert len(sahte.istekler) == ilk, "önbellek sayesinde tekrar istek atılmamalı"
    assert tmdb.istatistik()["cache"] >= 1
    await tmdb.aclose()


async def test_single_flight_eszamanli_cagrilarda_tek_istek():
    tmdb, sahte = istemci_uret()
    enricher = TMDBEnricher(tmdb, eszamanlilik=10)

    ogeler = [MovieInfo(url=f"https://s/{i}", title="The Matrix", release_date="1999")
              for i in range(10)]
    await enricher.zenginlestir_liste(ogeler, detay=True)

    arama = [p for p in sahte.istekler if "search" in p]
    assert len(arama) == 1, f"tek arama bekleniyordu, {len(arama)} yapıldı"
    await tmdb.aclose()


async def test_devre_kesici_ardik_hatalarda_istekleri_durdurur():
    tmdb, sahte = istemci_uret("500")
    tmdb.devre_esik = 2
    enricher = TMDBEnricher(tmdb)

    for i in range(4):
        await enricher.zenginlestir(MovieInfo(url=f"https://s/{i}", title=f"Benzersiz {i}"))

    assert tmdb.devrede() is True
    sayim = len(sahte.istekler)
    await enricher.zenginlestir(MovieInfo(url="https://s/x", title="Başka Biri"))
    assert len(sahte.istekler) == sayim, "devredeyken yeni istek atılmamalı"
    await tmdb.aclose()


# ── Liste güvenliği ──────────────────────────────────────────────────────────

async def test_liste_bir_oge_patlasa_digerleri_dokunulmaz():
    tmdb, _ = istemci_uret()
    enricher = TMDBEnricher(tmdb, zorunlu=False)

    class Bozuk:
        title = "Bozuk"
        poster = None

        @property
        def imdb_id(self):
            raise RuntimeError("patladı")

    ogeler = [
        MainPageResult(title="The Matrix", url="https://s/a", poster=None),
        Bozuk(),
        MainPageResult(title="The Matrix", url="https://s/b", poster=None),
    ]
    sonuc = await enricher.zenginlestir_liste(ogeler)

    assert len(sonuc) == 3
    assert sonuc[0].poster and sonuc[2].poster
    await tmdb.aclose()


async def test_bos_liste_kisa_yol():
    tmdb, _ = istemci_uret()
    enricher = TMDBEnricher(tmdb)
    assert await enricher.zenginlestir_liste([]) == []


# ── Anahtar türü ve yetkilendirme hatası ────────────────────────────────────

def test_anahtar_turu_tespiti():
    from Core.Libs.TMDB import _anahtar_turu

    assert _anahtar_turu("0123456789abcdef0123456789abcdef") == "v3"
    assert _anahtar_turu("A" * 31) == "bilinmiyor"
    assert _anahtar_turu("eyJhbGciOi.eyJzdWIiOi.SflKxwRJ") == "bilinmiyor"   # çok kısa JWT
    assert _anahtar_turu("eyJhbGciOiJIUzI1NiJ9." + "x" * 120 + ".sig") == "v4"
    assert _anahtar_turu("") == "bilinmiyor"


def test_gecersiz_anahtar_acilista_uyarilir():
    """Bilinmeyen biçimli anahtar, ilk istekten ÖNCE uyarı üretmeli."""
    tmdb = TMDBClient(api_key="bu-bir-token-degil")
    assert tmdb.anahtar_turu == "bilinmiyor"
    mesaj = tmdb.uyari_mesaji()
    assert mesaj and "API Key (v3 auth)" in mesaj


def test_gecerli_anahtarda_uyari_yok():
    assert TMDBClient(api_key="0123456789abcdef0123456789abcdef").uyari_mesaji() is None
    assert TMDBClient(api_key="").uyari_mesaji() is None


async def test_v3_anahtari_api_key_parametresiyle_gider():
    """v3 anahtarı sorgu parametresi olarak gönderilmeli."""
    tmdb, sahte = istemci_uret()
    tmdb.api_key = "0123456789abcdef0123456789abcdef"
    tmdb.anahtar_turu = "v3"

    gorulen = {}
    eski_handler = sahte.handler

    def yakala(request):
        gorulen.update(dict(request.url.params))
        gorulen["auth"] = request.headers.get("authorization")
        return eski_handler(request)

    tmdb._client = httpx.AsyncClient(transport=httpx.MockTransport(yakala), timeout=2.0)

    await tmdb.ara(title="The Matrix", year=1999)
    assert gorulen.get("api_key") == "0123456789abcdef0123456789abcdef"
    assert not gorulen.get("auth"), "v3'te Authorization başlığı gönderilmemeli"
    await tmdb.aclose()


async def test_v4_read_access_token_bearer_ile_gider():
    """Read Access Token (v4) Authorization başlığıyla gönderilmeli."""
    tmdb, sahte = istemci_uret()
    token = "eyJhbGciOiJIUzI1NiJ9." + "x" * 130 + ".sig"
    tmdb.api_key = token
    tmdb.anahtar_turu = "v4"

    gorulen = {}
    eski_handler = sahte.handler

    def yakala(request):
        gorulen.update(dict(request.url.params))
        gorulen["auth"] = request.headers.get("authorization")
        return eski_handler(request)

    tmdb._client = httpx.AsyncClient(transport=httpx.MockTransport(yakala), timeout=2.0)

    await tmdb.ara(title="The Matrix", year=1999)
    assert gorulen.get("auth") == f"Bearer {token}"
    assert "api_key" not in gorulen, "v4'te api_key parametresi gönderilmemeli"
    await tmdb.aclose()


async def test_yetki_hatasi_uzun_devre_acar_ve_tek_sefer_loglar(capsys):
    """
    401 mesajı MUTLAKA görünmeli.

    Bu test bir regresyon avıdır: mesaj üretimi sırasında oluşan herhangi bir
    hata (ad hatası, kodlama hatası) `_bellekli`'nin genel `except` bloğuna
    düşüp mesajı sessizce yutuyordu — kullanıcı yalnızca "başarısız: HTTP 401"
    görüyor, nedenini göremiyordu.
    """
    sahte = FakeTMDB("401")
    tmdb = TMDBClient(api_key="yanlis-anahtar")
    tmdb.yetki_hatasi_suresi = 900
    tmdb._client = sahte.istemci()

    assert await tmdb.ara(title="Matrix 1") is None
    cikti1 = capsys.readouterr().out

    assert "401" in cikti1, "401 mesajı basılmalı"
    assert "TMDB_API_KEY geçersiz" in cikti1, "anahtar hatası açıkça söylenmeli"
    assert "API Key (v3 auth)" in cikti1, "çözüm yolu gösterilmeli"
    assert "Invalid API key" in cikti1, "TMDB'nin kendi mesajı iletilmeli"

    # Uzun devre: sonraki denemelerde istek atılmamalı, log da tekrarlanmamalı.
    adet = len(sahte.istekler)
    for i in range(5):
        assert await tmdb.ara(title=f"Matrix {i}") is None
    assert len(sahte.istekler) == adet, "yetki hatasında istek yağdırılmamalı"
    assert capsys.readouterr().out == "", "ikinci kez uyarı basılmamalı"


async def test_401_tek_basarisiz_sayisi_degil_kalici_hatadir():
    """401 geçici hata sayılmaz; devre eşiği (5) biriktirilmez."""
    sahte = FakeTMDB("401")
    tmdb = TMDBClient(api_key="yanlis")
    tmdb._client = sahte.istemci()
    tmdb.yetki_hatasi_suresi = 900

    await tmdb.ara(title="Matrix")
    assert tmdb.devrede() is True
    assert tmdb.istatistik()["basarisiz"] >= 1
    await tmdb.aclose()


async def test_pazarlama_kelimeli_baslik_temizlenip_eslesir():
    """
    Regresyon: eklenti başlıkları kalabalıktır ("... izle", "Full Film Türkçe").

    Canlı ölçüm: TMDB `"Esaretin Bedeli izle"` sorgusuna 0 sonuç, temizlenmiş
    `"esaretin bedeli"` sorgusuna 1 sonuç döndü. Sorgu temizlenmeden gönderilirse
    Türkçe içeriklerin tamamı eşleşemiyordu.
    """
    tmdb, sahte = istemci_uret()
    enricher = TMDBEnricher(tmdb)

    oge = SearchResult(title="The Matrix izle", url="https://s/m", poster=None)
    sonuc = await enricher.zenginlestir(oge)

    assert sonuc.poster == "https://image.tmdb.org/t/p/w342/poster.jpg", "kirli başlık eşleşmeli"
    # Kritik: TMDB'ye KİRLİ başlık değil, temizlenmiş başlık gönderilmeli.
    assert sahte.sorgular == ["the matrix"], f"beklenmeyen sorgular: {sahte.sorgular}"
    await tmdb.aclose()


async def test_bolum_ibareli_baslik_temizlenip_eslesir():
    """
    Regresyon: DiziBox "Son Bölümler" kartları.

    Başlık "The Office 1.Sezon 2.Bölüm" biçimindeydi ve TMDB'ye aynen gönderiliyordu;
    sahte TMDB (canlı davranış gibi) böyle sorgulara 0 sonuç veriyor. Temizleme
    devrede olduğu için yine de eşleşmelidir.

    Not: `media_type="tv"` bilerek veriliyor (DiziBox yalnızca dizi döndürür) ve
    sahte sunucu "the office" için TV sonucu döndürüyor — yani film/dizi cezası
    da devreye giriyor ve doğru sonucu veriyor.
    """
    tmdb, sahte = istemci_uret()
    enricher = TMDBEnricher(tmdb)

    oge = MainPageResult(
        title="The Office 1.Sezon 2.Bölüm", url="https://s/m", poster=None,
        media_type="tv", season=1, episode=2,
    )
    sonuc = await enricher.zenginlestir(oge)

    assert sonuc.poster == "https://image.tmdb.org/t/p/w342/poster.jpg"
    assert sonuc.tmdb_id == 2316, "TV sonucu eşleşmeli"
    assert sahte.sorgular and "sezon" not in sahte.sorgular[0], sahte.sorgular
    assert "bölüm" not in sahte.sorgular[0], sahte.sorgular
    await tmdb.aclose()


async def test_media_tipi_cezasi_calisir():
    """`media_type="tv"` iken film sonucu kabul edilmemeli (DiziBox yalnızca dizi)."""
    tmdb, _ = istemci_uret()
    enricher = TMDBEnricher(tmdb)

    dizi_oldugu_halde = MainPageResult(title="The Matrix 1.Sezon 1.Bölüm", url="https://s/m",
                                       poster="https://s/kendi.jpg", media_type="tv")
    sonuc = await enricher.zenginlestir(dizi_oldugu_halde)
    assert sonuc.poster == "https://s/kendi.jpg", "tv ipucu ile film eşleşmemeli"

    tip_verilmezse = MainPageResult(title="The Matrix 1.Sezon 1.Bölüm", url="https://s/m", poster=None)
    sonuc2 = await enricher.zenginlestir(tip_verilmezse)
    assert sonuc2.poster == "https://image.tmdb.org/t/p/w342/poster.jpg", "tip yoksa eşleşmeli"
    await tmdb.aclose()


async def test_temiz_baslik_tek_sorgu_yeter():
    """Yinelenen (yalnız büyük/küçük harf farklı) sorgular elenir."""
    tmdb, sahte = istemci_uret()
    enricher = TMDBEnricher(tmdb)

    oge = SearchResult(title="The Matrix", url="https://s/m", poster=None)
    await enricher.zenginlestir(oge)
    assert sahte.sorgular == ["the matrix"], sahte.sorgular
    await tmdb.aclose()


async def test_sorgu_varyantlari_once_temizlenir():
    from Core.Libs.TMDB import TMDBClient as C

    assert C._sorgu_varyantlari("Esaretin Bedeli izle")[0] == "esaretin bedeli"
    assert C._sorgu_varyantlari("Esaretin Bedeli izle")[-1] == "Esaretin Bedeli izle"
    # Yalnız büyük/küçük harf farkı varsa tek varyant (gereksiz çift istek yok)
    assert len(C._sorgu_varyantlari("Matrix")) == 1
    assert len(C._sorgu_varyantlari("Matrix (1999) izle")) == 2


# ── API rota katmanı ─────────────────────────────────────────────────────────

class FakeEnricher:
    """Zenginleştiricinin rota katmanındaki davranışını taklit eder."""

    def __init__(self, aktif=True, patlat=False):
        self.aktif = aktif
        self.patlat = patlat
        self.cagri = 0

    async def zenginlestir(self, oge, detay=False):
        self.cagri += 1
        if self.patlat:
            raise RuntimeError("zenginleştirme patladı")
        return oge

    async def zenginlestir_liste(self, ogeler, detay=False):
        self.cagri += len(ogeler)
        if self.patlat:
            raise RuntimeError("zenginleştirme patladı")
        return ogeler


async def test_rota_tmdb_kapaliyken_hicbir_zaman_cagri_yapmaz(monkeypatch):
    pytest.importorskip("fastapi")
    from api.routes import plugins as rotalar

    sahte = FakeEnricher(aktif=False)
    monkeypatch.setattr(rotalar, "get_tmdb_enricher", lambda: sahte)

    oge = SearchResult(title="X", url="https://s/x", poster="https://s/p.jpg")
    assert await rotalar._zenginlestir(oge) is oge
    assert await rotalar._zenginlestir_liste([oge, oge]) == [oge, oge]
    assert sahte.cagri == 0, "TMDB kapalıyken gereksiz iş yapılmamalı"


async def test_rota_aktifken_zenginlestirir(monkeypatch):
    pytest.importorskip("fastapi")
    from api.routes import plugins as rotalar

    sahte = FakeEnricher(aktif=True)
    monkeypatch.setattr(rotalar, "get_tmdb_enricher", lambda: sahte)

    oge = SearchResult(title="X", url="https://s/x")
    await rotalar._zenginlestir(oge, detay=True)
    await rotalar._zenginlestir_liste([oge, oge, oge])

    assert sahte.cagri == 4


async def test_rota_zenginlestirici_cokerse_istek_dusmez(monkeypatch):
    """Zenginleştirme patlasa bile endpoint çalışmaya devam etmeli."""
    pytest.importorskip("fastapi")
    from api.routes import plugins as rotalar

    monkeypatch.setattr(rotalar, "get_tmdb_enricher", lambda: FakeEnricher(True, patlat=True))

    oge = SearchResult(title="X", url="https://s/x", poster="https://s/p.jpg")
    sonuc = await rotalar._zenginlestir(oge)
    liste = await rotalar._zenginlestir_liste([oge])

    assert sonuc is oge and sonuc.poster == "https://s/p.jpg"
    assert liste == [oge]