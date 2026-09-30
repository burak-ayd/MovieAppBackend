# Bu araç @keyiflerolsun tarafından | @KekikAkademi için yazılmıştır.
# Python portu: Kekik-cloudstream / DiziPalOriginal.kt
#
# Oynatıcı zinciri (canlı doğrulandı):
#   1) Bölüm sayfası  -> #videoContainer[data-cfg] (token) + PHPSESSID çerezi
#   2) POST /ajax-player-config {cfg: token}  -> config.enc {k1, k2, iv, c}
#   3) anahtar = XOR(k1, k2)  ->  AES-CBC/PKCS5 çözme  ->  embed adresi
#   4) Embed sayfası  ->  `sources:[{file:"...m3u8"}]`  (yoksa `v:"....html"`
#      -> id çıkarılıp superadjacentsoddenly master.m3u8 kurulur)
#      imagestoo ise kendi API'sinden `securedLink` alınır.
#
# Kategori sayfalaması `?page=N` ile çalışır; kök sayfa (`Ana Sayfa`) sayfalanmaz.

import base64
import json
import re
from typing import Any, Dict, List, Optional, Union

from bs4 import BeautifulSoup
from cryptography.hazmat.primitives import padding as crypto_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from Core.Extractor.ExtractorModels import ExtractResult, Subtitle
from Core.Plugin.PluginBase import PluginBase
from Core.Plugin.PluginModels import Episode, MainPageResult, MovieInfo, SearchResult, SeriesInfo


USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

AJAX_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}


def _b64_bytes(metin: str) -> bytes:
    """URL-güvenli Base64 çözme (Kotlin b64ToBytes)."""
    temiz = (metin or "").replace("-", "+").replace("_", "/")
    temiz += "=" * (-len(temiz) % 4)
    return base64.b64decode(temiz)


def _xor(a: bytes, b: bytes) -> bytes:
    """Kotlin xorBytes: iki anahtarı bayt bayt XOR."""
    return bytes(x ^ y for x, y in zip(a, b))


# Kategori yolları (Kotlin mainPageOf listesi). "Ana Sayfa" ayrıca eklenir.
_KATEGORILER: tuple = (
    ("/bolumler",                 "Son Bölümler"),
    ("/diziler",                  "Yeni Diziler"),
    ("/filmler",                  "Yeni Filmler"),
    ("/platform/netflix",         "Netflix"),
    ("/platform/exxen",           "Exxen"),
    ("/platform/blutv",           "BluTV"),
    ("/platform/disney-plus",     "Disney+"),
    ("/platform/prime-video",     "Amazon Prime"),
    ("/platform/tabii",           "Tabii"),
    ("/platform/gain",            "Gain"),
    ("/platform/max",             "Max"),
    ("/kategori/bilim-kurgu",     "Bilimkurgu Filmleri"),
    ("/kategori/komedi",          "Komedi Filmleri"),
    ("/kategori/belgesel",        "Belgesel Filmleri"),
)


def kategori_sayfasi(main_url: str) -> Dict[str, str]:
    """Ana sayfa sözlüğü. İlk sıra her zaman "Ana Sayfa" (kök adres).

    Kategori adresleri sayfasız tutulur; `get_main_page` `?page=N` ekler.
    """
    kok = main_url.rstrip("/")
    sayfalar: Dict[str, str] = {"Ana Sayfa": kok}
    for yol, ad in _KATEGORILER:
        sayfalar[ad] = f"{kok}{yol}"
    return sayfalar


class DiziPalOriginal(PluginBase):
    """DiziPal (dizipal2134.com) — dizi + film."""

    name        = "DiziPalOriginal"
    language    = "tr"
    main_url    = "https://dizipal2134.com"
    description = "DiziPal - Dizi ve film izleme platformu"
    favicon     = f"https://www.google.com/s2/favicons?domain={main_url}&sz=64"

    # Kategori listesi: "Ana Sayfa" (kök) + 14 kategori. Sayfalama `?page=N`.
    main_page: Dict[str, str] = kategori_sayfasi(main_url)

    # ================================================================== #
    # Yardımcılar
    # ================================================================== #

    @staticmethod
    def _temizle(deger: Optional[str]) -> str:
        return re.sub(r"\s+", " ", (deger or "")).strip()

    def _json_ld(self, html: str, tur: tuple = ("Movie", "TVSeries")) -> Dict[str, Any]:
        """Sayfadaki JSON-LD bloğundan Film/Dizi kaydını döndürür."""
        for blok in re.findall(r"<script[^>]*>(.*?)</script>", html, re.S):
            govde = blok.strip()
            if "@context" not in govde:
                continue
            try:
                veri = json.loads(govde)
            except Exception:
                continue
            kayitlar = veri if isinstance(veri, list) else [veri]
            for kayit in kayitlar:
                if isinstance(kayit, dict) and kayit.get("@type") in tur:
                    return kayit
        return {}

    @staticmethod
    def _iso_sure(deger: Optional[str]) -> Optional[int]:
        """ISO 8601 süre: "PT93M" -> 93."""
        if not deger:
            return None
        m = re.search(r"PT(?:(\d+)H)?(?:(\d+)M)?", str(deger))
        if not m:
            return None
        saat, dakika = m.group(1), m.group(2)
        if not (saat or dakika):
            return None
        return int(saat or 0) * 60 + int(dakika or 0)

    def _bilgi_satirlari(self, soup) -> Dict[str, str]:
        """`div.info-row` satırlarını {etiket: değer} sözlüğüne çevirir."""
        satirlar: Dict[str, str] = {}
        for satir in soup.select("div.info-row"):
            etiket = satir.select_one("span.info-label, .info-label")
            deger = satir.select_one("span.info-value")
            anahtar = self._temizle(etiket.get_text() if etiket else "")
            if not anahtar:
                tum = self._temizle(satir.get_text(" "))
                parcalar = tum.split(" ", 1)
                anahtar, deger_metin = (parcalar[0], parcalar[1] if len(parcalar) > 1 else "")
            else:
                deger_metin = self._temizle(deger.get_text(" ") if deger else "")
            if anahtar:
                satirlar[anahtar] = deger_metin
        return satirlar

    def _bolum_url(self, bolum_url: str) -> str:
        """Bölüm adresinden dizi adresine: /bolum/x-4-sezon-9-bolum -> /dizi/x"""
        return re.sub(r"-\d+-sezon.*$", "", bolum_url.replace("/bolum/", "/dizi/"))

    # ================================================================== #
    # Zorunlu metotlar
    # ================================================================== #

    async def get_main_page(self, page: int = 1, url: str = "", category: str = "") -> List[MainPageResult]:
        page = max(1, int(page or 1))
        kok = self.main_url.rstrip("/")
        temel = (url or "").strip().rstrip("/")

        if not temel or temel == kok:
            # Ana sayfa: hem dizi/film kartları hem bölüm kartları, sayfalanmaz
            html = await self.async_cf_get(kok)
            soup = BeautifulSoup(html or "", "html.parser")
            return self._icerik_kartlari(soup, category) + self._bolum_kartlari(soup, category)

        # Kategoriler `?page=N` ile sayfalanıyor
        hedef = f"{temel}?page={page}"
        html = await self.async_cf_get(hedef)
        soup = BeautifulSoup(html or "", "html.parser")

        if "/bolumler" in temel:
            return self._bolum_kartlari(soup, category)
        return self._icerik_kartlari(soup, category)

    def _icerik_kartlari(self, soup, category: str) -> List[MainPageResult]:
        """Kotlin diziler(): `ul.content-grid > li`"""
        kartlar: List[MainPageResult] = []
        for li in soup.select("ul.content-grid > li"):
            baslik_el = li.select_one("div.card-info h3")
            if not baslik_el:
                continue
            baslik = self._temizle(baslik_el.get_text())
            a = li.select_one("a[href]")
            if not baslik or not a:
                continue
            img = li.select_one("img")
            poster = None
            if img:
                poster = img.get("data-src") or img.get("src")
                poster = self.fix_url(poster) if poster else None

            adres = self.fix_url(a.get("href") or "")
            kartlar.append(MainPageResult(
                title      = baslik,
                url        = adres,
                category   = category,
                poster     = poster,
                media_type = "Film" if "/film/" in adres else "Dizi",
            ))
        return kartlar

    def _bolum_kartlari(self, soup, category: str) -> List[MainPageResult]:
        """Kotlin sonBolumler(): `div.episodes-list-grid > a.episode-list-item`"""
        kartlar: List[MainPageResult] = []
        for a in soup.select("div.episodes-list-grid > a.episode-list-item"):
            baslik_el = a.select_one(".ep-title")
            info_el = a.select_one(".ep-info")
            if not baslik_el or not info_el:
                continue

            baslik = self._temizle(baslik_el.get_text())
            bolum = self._temizle(info_el.get_text())
            # "4. Sezon 9. Bölüm" -> "4x9"
            bolum = bolum.replace(". Sezon", "x").replace(". Bölüm", "").strip()
            if not baslik or not bolum:
                continue

            href = a.get("href") or ""
            adres = self.fix_url(href)
            if not adres:
                continue
            img = a.select_one("img")
            poster = None
            if img:
                poster = img.get("data-src") or img.get("src")
                poster = self.fix_url(poster) if poster else None

            sezon = bolum_no = None
            m = re.match(r"^(\d+)x(\d+)$", bolum)
            if m:
                sezon, bolum_no = int(m.group(1)), int(m.group(2))

            kartlar.append(MainPageResult(
                title      = f"{baslik} {bolum}",
                url        = self._bolum_url(adres),
                category   = category,
                poster     = poster,
                season     = sezon,
                episode    = bolum_no,
                media_type = "Dizi",
            ))
        return kartlar

    async def search(self, query: str) -> List[SearchResult]:
        """Kotlin search(): /ajax-search?q= (JSON)"""
        url = f"{self.main_url.rstrip('/')}/ajax-search?q={query.strip()}"
        html = await self.async_cf_get(url, headers=AJAX_HEADERS)

        try:
            veri = json.loads(html or "{}")
        except Exception:
            return []

        sonuclar: List[SearchResult] = []
        for item in (veri.get("results") or []):
            if not isinstance(item, dict):
                continue
            baslik = item.get("title")
            adres = item.get("url")
            if not baslik or not adres:
                continue
            dizi_mi = str(item.get("type") or "").lower() == "dizi"
            sonuclar.append(SearchResult(
                title      = baslik,
                url        = self.fix_url(adres),
                poster     = item.get("poster"),
                year       = item.get("year"),
                media_type = "Dizi" if dizi_mi else "Film",
            ))
        return sonuclar

    async def load_item(self, url: str) -> Union[MovieInfo, SeriesInfo]:
        # Bölüm adresi -> dizi adresi
        if "/bolum/" in url:
            url = self._bolum_url(url)

        html = await self.async_cf_get(url)
        soup = BeautifulSoup(html or "", "html.parser")
        satirlar = self._bilgi_satirlari(soup)
        ld = self._json_ld(html)

        poster_el = soup.select_one('meta[property="og:image"]')
        poster = poster_el.get("content") if poster_el else None

        if "/dizi/" in url:
            baslik_el = soup.select_one("h1.series-title")
            baslik = self._temizle(baslik_el.get_text() if baslik_el else (ld.get("name") or ""))

            bolumler: List[Episode] = []
            for sarmalayici in soup.select("div.detail-episode-item-wrap"):
                a = sarmalayici.select_one("a.detail-episode-item")
                if not a:
                    continue
                ad = a.get("href")
                isim_el = a.select_one("div.detail-episode-title")
                alt_el = a.select_one("div.detail-episode-subtitle")
                isim = self._temizle(isim_el.get_text() if isim_el else "")
                alt = self._temizle(alt_el.get_text() if alt_el else "")

                sezon = bolum = None
                m = re.search(r"(\d+)\.\s*[Ss]ezon\s*(\d+)\.\s*[Bb]ölüm", alt)
                if m:
                    sezon, bolum = int(m.group(1)), int(m.group(2))
                else:
                    m2 = re.search(r"(\d+)[xX](\d+)", alt or isim)
                    if m2:
                        sezon, bolum = int(m2.group(1)), int(m2.group(2))
                if sezon is None:
                    # Adres sonundan: /bolum/<slug>-4-sezon-9-bolum
                    m3 = re.search(r"-(\d+)-sezon-(\d+)-bolum", a.get("href") or "")
                    if m3:
                        sezon, bolum = int(m3.group(1)), int(m3.group(2))

                if not ad or not isim:
                    continue
                # Episode modeli "sezon/bölüm" içeren başlıkları boşaltıyor; site
                # başlığın sonuna "N.Sezon N.Bölüm" eklediği için burada ayıklıyoruz.
                temiz_isim = re.sub(r"\s*\d+\s*\.\s*Sezon.*$", "", isim, flags=re.I).strip()
                if not temiz_isim:
                    temiz_isim = isim
                bolumler.append(Episode(
                    url     = self.fix_url(ad),
                    title   = temiz_isim,
                    season  = sezon,
                    episode = bolum,
                ))

            # Sözleşme: seasons = {sezon_no: [Episode, ...]}
            sezonlar: Dict[Any, List[Episode]] = {}
            for b in bolumler:
                sezonlar.setdefault(b.season if b.season is not None else 1, []).append(b)
            for liste in sezonlar.values():
                liste.sort(key=lambda b: (b.episode if b.episode is not None else 0))

            sezon_sayisi = None
            m = re.search(r"(\d+)\s*Sezon", satirlar.get("Toplam", "") or "", re.I)
            if m:
                sezon_sayisi = int(m.group(1))
            if not sezon_sayisi and sezonlar:
                sezon_sayisi = max(sezonlar)

            puan = None
            m = re.search(r"(\d+[.,]\d+)", satirlar.get("IMDB", "") or "")
            if m:
                puan = m.group(1).replace(",", ".")

            return SeriesInfo(
                content_type = "series",
                url          = url,
                title        = baslik or None,
                poster       = poster,
                description  = self._temizle(
                    (soup.select_one("p.series-description").get_text(" ")
                     if soup.select_one("p.series-description") else ld.get("description"))
                ) or None,
                year        = satirlar.get("Yıl") or (str(ld["datePublished"]) if ld.get("datePublished") else None),
                rating      = puan,
                tags        = satirlar.get("Kategoriler") or None,
                seasons     = sezonlar or None,
            )

        # ---- Film ----
        baslik_el = soup.select_one("h1.series-title, h1.movie-title")
        baslik = ""
        if baslik_el:
            baslik = self._temizle(baslik_el.get_text())
        if not baslik:
            og = soup.select_one('meta[property="og:title"]')
            if og:
                baslik = (og.get("content") or "").split(" izle")[0].split("|")[0].strip()
        if not baslik:
            baslik = self._temizle(ld.get("name") or "")

        ozet = ""
        d = soup.select_one("p.series-description")
        if d:
            ozet = self._temizle(d.get_text(" "))
        if not ozet:
            og = soup.select_one('meta[property="og:description"]')
            ozet = self._temizle(og.get("content")) if og else self._temizle(ld.get("description") or "")

        yil = None
        if ld.get("datePublished"):
            yil = str(ld["datePublished"])
        else:
            m = re.search(r"\((19\d{2}|20\d{2})\)", ozet)
            yil = m.group(1) if m else None

        puan = None
        toplam = ld.get("aggregateRating") or {}
        if isinstance(toplam, dict):
            deger = toplam.get("ratingValue")
            try:
                # Sitede puanı olmayan içeriklerde "0.0" geliyor -> puan yok sayılır
                sayi = float(str(deger).replace(",", ".")) if deger not in (None, "") else 0.0
                puan = str(deger) if sayi > 0 else None
            except (TypeError, ValueError):
                puan = None

        return MovieInfo(
            content_type    = "movie",
            url             = url,
            title           = baslik or None,
            description     = ozet or None,
            poster_url      = poster,
            release_date    = yil,
            runtime_minutes = self._iso_sure(ld.get("duration")) or 0,
            rating          = puan,
            genre           = satirlar.get("Kategoriler").split(", ") if satirlar.get("Kategoriler") else [],
            is_featured     = True,
        )

    # ================================================================== #
    # Oynatıcı
    # ================================================================== #

    def _enc_coz(self, enc: Dict[str, str]) -> str:
        """Kotlin decryptEnc: XOR(k1,k2) -> AES-CBC/PKCS5 çözme."""
        try:
            k1 = _b64_bytes(enc.get("k1", ""))
            k2 = _b64_bytes(enc.get("k2", ""))
            iv = _b64_bytes(enc.get("iv", ""))
            ct = _b64_bytes(enc.get("c", ""))
        except Exception as e:
            print(f"[!] {self.name} base64 çözme hatası: {e}")
            return ""

        anahtar = _xor(k1, k2)
        if len(anahtar) not in (16, 24, 32):
            print(f"[!] {self.name} geçersiz anahtar uzunluğu: {len(anahtar)}")
            return ""

        try:
            cozucu = Cipher(algorithms.AES(anahtar), modes.CBC(iv)).decryptor()
            duz = cozucu.update(ct) + cozucu.finalize()
            geri = crypto_padding.PKCS7(128).unpadder()
            return (geri.update(duz) + geri.finalize()).decode("utf-8", "replace").strip()
        except Exception as e:
            print(f"[!] {self.name} AES çözme hatası: {e}")
            return ""

    async def load_links(self, url: str) -> List[ExtractResult]:
        """Bölüm/film sayfasından doğrudan m3u8 + altyazı üretir."""
        bolum_sayfasi = await self.httpx.get(url, headers={
            "User-Agent": USER_AGENT, "Cache-Control": "no-cache", "Pragma": "no-cache",
        }, timeout=30.0)
        bolum_sayfasi.raise_for_status()

        token = None
        m = re.search(r'id="videoContainer"[^>]*?data-cfg="([^"]*)"', bolum_sayfasi.text) \
            or re.search(r'data-cfg="([^"]*)"', bolum_sayfasi.text)
        if m:
            token = m.group(1).strip()
        if not token:
            print(f"[!] {self.name}: data-cfg token bulunamadı ({url})")
            return []

        # Çerezleri topla (PHPSESSID vb.)
        cerezler = [x.split(";")[0].strip() for x in bolum_sayfasi.headers.get_list("set-cookie")
                    if "=" in x]
        cerez = "; ".join(dict.fromkeys(cerezler))
        basliklar = dict(AJAX_HEADERS)
        basliklar["Referer"] = url
        if cerez:
            basliklar["Cookie"] = cerez

        if token.startswith("{"):
            config = token
        else:
            yanit = await self.httpx.post(
                f"{self.main_url.rstrip('/')}/ajax-player-config",
                data={"cfg": token}, headers=basliklar,
            )
            try:
                config = yanit.json()
            except Exception as e:
                print(f"[!] {self.name}: player config JSON değil ({e})")
                return []

        enc = (config or {}).get("enc")
        if not isinstance(enc, dict):
            print(f"[!] {self.name}: 'enc' nesnesi yok")
            return []

        embed = self.fix_url(self._enc_coz(enc))
        if not embed:
            print(f"[!] {self.name}: embed adresi çözülemedi")
            return []

        if "imagestoo" in embed:
            try:
                return await self._imagestoo_coz(embed, url)
            except Exception as e:
                # imagestoo.com arıza durumunda (HTTP 523 / zaman aşımı) olabiliyor
                print(f"[!] {self.name}: imagestoo çözülemedi ({e}); bu kaynak atlandı.")
                return []

        try:
            return await self._embed_coz(embed, url)
        except Exception as e:
            print(f"[!] {self.name}: embed sayfası okunamadı ({e})")
            return []

    async def _embed_coz(self, embed: str, referer: str) -> List[ExtractResult]:
        """Embed sayfasından m3u8 + altyazılar (Kotlin ana sunucu dalı)."""
        # CDN sunucuları yavaş yanıt verebiliyor; istemci varsayılanı 10 sn
        yanit = await self.httpx.get(embed, headers={"User-Agent": USER_AGENT, "Referer": referer},
                                    timeout=30.0)
        yanit.raise_for_status()
        govde = yanit.text

        m3u8 = re.search(r'sources\s*:\s*\[\s*\{\s*file\s*:\s*["\']([^"\']+\.m3u8.*?)["\']', govde)
        if not m3u8:
            v = re.search(r'v\s*:\s*["\']([^"\']+\.html.*?)["\']', govde)
            if not v:
                print(f"[!] {self.name}: embed içinde m3u8 bulunamadı ({embed})")
                return []
            kimlik = re.search(r"embed-([^.]+)\.html", v.group(1))
            if not kimlik:
                print(f"[!] {self.name}: embed ID çıkarılamadı ({v.group(1)})")
                return []
            m3u8_url = (f"https://s2.superadjacentsoddenly.xyz/hls2/01/00007/"
                        f"{kimlik.group(1)}_,n,h,.urlset/master.m3u8")
        else:
            m3u8_url = m3u8.group(1)

        altyazilar: List[Subtitle] = []
        blok = re.search(r"tracks\s*:\s*\[(.*?)\]", govde, re.S)
        if blok:
            for parca in re.finditer(r"\{(.*?)\}", blok.group(1), re.S):
                govde_parca = parca.group(1)
                dosya = re.search(r'file\s*:\s*["\']([^"\']+)["\']', govde_parca)
                etiket = re.search(r'label\s*:\s*["\']([^"\']+)["\']', govde_parca)
                if not dosya:
                    continue
                if not dosya.group(1).lower().endswith((".vtt", ".srt")):
                    continue
                altyazilar.append(Subtitle(
                    name = self._temizle(etiket.group(1)) if etiket else "Turkish",
                    url  = self.fix_url(dosya.group(1).replace("\\/", "/")),
                ))

        return [ExtractResult(
            name      = "DiziPal (Ana Sunucu)",
            url       = self.fix_url(m3u8_url),
            referer   = embed,
            headers   = {"Referer": embed},
            subtitles = altyazilar,
        )]

    async def _imagestoo_coz(self, embed: str, referer: str) -> List[ExtractResult]:
        """Imagestoo dalı: kendi API'sinden securedLink + oturum çerezi."""
        video_id = embed.rstrip("/").split("/")[-1]
        api = f"https://imagestoo.com/player/index.php?data={video_id}&do=getVideo"

        yanit = await self.httpx.post(api, headers={
            "User-Agent": USER_AGENT, "X-Requested-With": "XMLHttpRequest",
            "Accept": "*/*", "Referer": embed,
        }, timeout=20.0)

        cerez = ""
        for ham in yanit.headers.get_list("set-cookie"):
            if "fireplayer_player" in ham:
                cerez = ham.split(";")[0].strip() + ";"
                break

        m = re.search(r'"securedLink"\s*:\s*"([^"]+)"', yanit.text)
        if not m:
            print(f"[!] {self.name}: imagestoo securedLink bulunamadı")
            return []

        return [ExtractResult(
            name      = "DiziPal (Imagestoo)",
            url       = self.fix_url(m.group(1).replace("\\/", "/")),
            referer   = embed,
            headers   = {"Referer": embed, **({"Cookie": cerez} if cerez else {})},
        )]