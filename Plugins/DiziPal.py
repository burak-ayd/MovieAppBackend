# Bu araç @keyiflerolsun tarafından | @KekikAkademi için yazılmıştır.
# Python portu: Kekik-cloudstream / DiziPal.kt
#
# Oynatıcı zinciri (canlı doğrulandı):
#   1) Bölüm sayfası -> `div[data-rm-k=true]` içinde {ciphertext, iv, salt}
#   2) PBKDF2-HMAC-SHA512(passphrase, salt, 999 tur, 256 bit) -> AES-256-CBC/PKCS5
#      -> iframe adresi (https://four.dplayer82.site/iframe.php?v=...)
#   3) iframe adresi ExtractorManager'a bırakılır; dplayer82.site host'u repodaki
#      ContentX oynatıcısı (SNplayer) tarafından çözülür:
#      openPlayer() -> source2.php -> m.php -> master.m3u8 (+ altyazılar)
#
# Siteden sapan yerler (Kotlin'dan farklı, canlı doğrulandı):
#   * Kategori sayfaları `?sayfa=N` ile sayfalanmıyor (üç sayfa da birebir aynı).
#     Yalnızca kanal sayfaları `/bg/getserielistbychannel` API'si üzerinden
#     `curPage` ile sayfalanıyor.
#   * Film yolu `/movies/<slug>`; Kotlin'ın `//div[@class='g-title'][2]/div`
#     XPath'i sayfada yok, başlık `h1` içinde.
#   * Film sayfasında afiş görseli sunucu tarafında basılmıyor (dizilerde var).

import asyncio
import base64
import json
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from bs4 import BeautifulSoup
from cryptography.hazmat.primitives import hashes, padding as crypto_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from Core.Plugin.PluginBase import PluginBase
from Core.Plugin.PluginModels import Episode, MainPageResult, MovieInfo, SearchResult, SeriesInfo

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

AJAX_HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}

# /bg/* uçlarının istediği kimlik bilgileri her sayfada gizli input olarak gelir ve
# SÜRELİDİR (Kotlin'deki sabit değerler zamanla geçersizleşiyor). Bu yüzden
# `_tokens()` ile sayfadan taze alınır.
ESKI_C_KEY = "c61f91c5141d178450934fe81c0a2029"
ESKI_C_VALUE = ("MTc4NDQwNzIwMDhkMzJhNTc1YzUwOGU1ZjQwMjdjMjIyOWVjOGVhMTcwNGQyM2FjODM2YTI4YTU0NjUyMjI2"
                "ZmVjMzFkYzBkMWQyMWY4YzdiNA==")

# decryptDizipalData() içindeki sabit parola
IFRAME_PASSPHRASE = (
    "3hPn4uCjTVtfYWcjIcoJQ4cL1WWk1qxXI39egLYOmNv6IblA7eKJz68uU3eLzux1biZLCms0quEjTYniGv5z1JcKbNIsDQFSeIZOBZ"
    "Jz4is6pD7UyWDggWWzTLBQbHcQFpBQdClnuQaMNUHtLHTpzCvZy33p6I7wFBvL4fnXBYH84aUIyWGTRvM2G5cfoNf4705tO2kv"
)

# (yol, görünen ad) — Kotlin mainPageOf listesi
_KATEGORILER: tuple = (
    ("/yabanci-dizi-izle",  "Yeni Diziler"),
    ("/hd-film-izle",       "Yeni Filmler"),
    ("/kanal/netflix",      "Netflix"),
    ("/kanal/exxen",        "Exxen"),
    ("/kanal/max",          "Max"),
    ("/kanal/disney",       "Disney+"),
    ("/kanal/amazon",       "Amazon Prime"),
    ("/kanal/tod",          "TOD (beIN)"),
    ("/kanal/tabii",        "Tabii"),
    ("/kanal/hulu",         "Hulu"),
)


def kategori_sayfasi(main_url: str) -> Dict[str, str]:
    """Ana sayfa sözlüğü. İlk sıra her zaman "Ana Sayfa" (kök adres)."""
    kok = main_url.rstrip("/")
    sayfalar: Dict[str, str] = {"Ana Sayfa": kok}
    for yol, ad in _KATEGORILER:
        sayfalar[ad] = f"{kok}{yol}"
    return sayfalar


class DiziPal(PluginBase):
    """DiziPal (dizipal1584.com) — dizi + film."""

    name        = "DiziPal"
    language    = "tr"
    main_url    = "https://dizipal1584.com"
    description = "DiziPal - Dizi ve film izleme platformu"
    favicon     = f"https://www.google.com/s2/favicons?domain={main_url}&sz=64"

    main_page: Dict[str, str] = kategori_sayfasi(main_url)

    # /bg/* uçları için taze cKey/cValue önbelleği
    _token_cache: Optional[Tuple[str, str]] = None

    # ================================================================== #
    # Yardımcılar
    # ================================================================== #

    async def _tokens(self) -> Tuple[str, str]:
        """Sayfadan gizli input'lardaki güncel `cKey` / `cValue` değerlerini alır.

        Bu değerler süreli olduğu için her istekte değil, önbellek boşken okunur.
        """
        if self._token_cache:
            return self._token_cache

        for yol in ("/arama-yap", "/", "/yabanci-dizi-izle"):
            try:
                html = await self.async_cf_get(f"{self.main_url.rstrip('/')}{yol}")
            except Exception:
                continue
            ck = re.search(r'name="cKey"\s+value="([^"]+)"', html or "")
            cv = re.search(r'name="cValue"\s+value="([^"]+)"', html or "")
            if ck and cv:
                self._token_cache = (ck.group(1), cv.group(1))
                return self._token_cache

        # Sayfadan okunamadıysa gömülü değerlere düş
        self._token_cache = (ESKI_C_KEY, ESKI_C_VALUE)
        return self._token_cache

    async def _bg_post(self, yol: str, veri: Dict[str, str], referer: str, deneme: int = 3) -> Optional[dict]:
        """POST /bg/* — 429 (hız sınırı) ve JSON hatalarında kısa bekleyerek yeniden dener."""
        son_hata = ""
        for i in range(deneme):
            c_key, c_value = await self._tokens()
            govde = {**veri, "cKey": c_key, "cValue": c_value}
            try:
                yanit = await self.httpx.post(
                    f"{self.main_url.rstrip('/')}{yol}", data=govde,
                    headers={**AJAX_HEADERS, "User-Agent": USER_AGENT, "Referer": referer},
                    timeout=30.0,
                )
            except Exception as e:
                son_hata = str(e)[:50]
                await asyncio.sleep(1.2 * (i + 1))
                continue

            if yanit.status_code == 200:
                try:
                    return yanit.json()
                except Exception:
                    son_hata = "JSON değil"
            else:
                son_hata = f"HTTP {yanit.status_code}"
                if yanit.status_code not in (429, 503):
                    break

            # Hız sınırı: bekleyip tekrar dene
            await asyncio.sleep(2.0 * (i + 1))

        print(f"[!] {self.name}: {yol} isteği başarısız ({son_hata})")
        return None

    @staticmethod
    def _temizle(deger: Optional[str]) -> str:
        return re.sub(r"\s+", " ", (deger or "")).strip()

    def _sayfa_basi(self, url: str) -> str:
        return f"{self.main_url.rstrip('/')}{url}"

    def _kart(self, div, category: str) -> Optional[MainPageResult]:
        """`div.bg-[#22232a]` kartı -> MainPageResult (Kotlin diziler())."""
        img = div.select_one("img")
        a = div.select_one("a[href]")
        if not img or not a:
            return None

        baslik = self._temizle(img.get("alt"))
        adres = self.fix_url(a.get("href") or "")
        if not baslik or not adres:
            return None

        poster = img.get("data-src") or img.get("src")
        return MainPageResult(
            title      = baslik,
            url        = adres,
            category   = category,
            poster     = self.fix_url(poster) if poster else None,
            media_type = "movie" if "/movies/" in adres else "series",
        )

    def _html_kartlari(self, soup, category: str) -> List[MainPageResult]:
        kartlar = [self._kart(d, category) for d in soup.select("div.bg-\\[\\#22232a\\]")]
        return [k for k in kartlar if k]

    def _bilgi(self, soup, etiket: str) -> Optional[str]:
        """`//div[text()='Yıl']//following-sibling::div` karşılığı."""
        for d in soup.find_all("div", string=lambda x: x and x.strip() == etiket):
            komsu = d.find_next_sibling("div")
            if komsu:
                return self._temizle(komsu.get_text(" "))
        return None

    # ================================================================== #
    # Zorunlu metotlar
    # ================================================================== #

    async def get_main_page(self, page: int = 1, url: str = "", category: str = "") -> List[MainPageResult]:
        page = max(1, int(page or 1))
        kok = self.main_url.rstrip("/")
        temel = (url or "").strip().rstrip("/")

        # Ana sayfa
        if not temel or temel == kok:
            soup = BeautifulSoup(await self.async_cf_get(kok) or "", "html.parser")
            return self._html_kartlari(soup, category)

        yol = temel[len(kok):] if temel.startswith(kok) else temel

        # Kanal sayfaları: HTML + sayfalanan API
        if "/kanal/" in yol:
            kartlar = self._html_kartlari(
                BeautifulSoup(await self.async_cf_get(temel) or "", "html.parser"), category)
            api = await self._kanal_api(yol.rsplit("/", 1)[-1], page, category)
            mevcut = {k.url for k in kartlar}
            kartlar += [k for k in api if k.url not in mevcut]
            return kartlar

        # Normal kategoriler sayfalanmıyor: 1. sayfa listenin tamamı, sonrası boş
        if page > 1:
            return []
        soup = BeautifulSoup(await self.async_cf_get(temel) or "", "html.parser")
        return self._html_kartlari(soup, category)

    async def _kanal_api(self, slug: str, page: int, category: str) -> List[MainPageResult]:
        """POST /bg/getserielistbychannel -> data.html (sayfalanan kanal listesi)."""
        veri = await self._bg_post(
            "/bg/getserielistbychannel",
            {"curPage": str(page), "channelId": "1", "languageId": "2,3,4", "slug": slug},
            self._sayfa_basi(f"/kanal/{slug}"),
        )
        if not veri:
            return []

        html = ((veri.get("data") or {}).get("html") or "")
        if not html:
            return []
        return self._html_kartlari(BeautifulSoup(html, "html.parser"), category)

    async def search(self, query: str) -> List[SearchResult]:
        """POST /bg/searchcontent -> data.result

        Alan adları Kotlin'ın SearchItem modelinden farklıdır
        (`object_name` / `used_slug` / `used_type` / `object_poster_url`).
        """
        veri = await self._bg_post(
            "/bg/searchcontent",
            {"type": "hepsi", "searchterm": query.strip()},
            f"{self.main_url.rstrip('/')}/arama-yap",
        )
        if not veri:
            return []

        sonuclar: List[SearchResult] = []
        for item in ((veri.get("data") or {}).get("result") or []):
            if not isinstance(item, dict):
                continue
            baslik = self._temizle(item.get("object_name") or item.get("title"))
            slug = item.get("used_slug") or item.get("slug") or ""
            if not baslik or not slug:
                continue

            tur = str(item.get("used_type") or item.get("type") or "").lower()
            dizi_mi = "series" in tur or "dizi" in tur

            adres = slug if str(slug).startswith("http") else f"{self.main_url.rstrip('/')}/{str(slug).lstrip('/')}"
            yil = item.get("object_release_year") or item.get("year")
            puan = item.get("object_related_imdb_point")

            sonuclar.append(SearchResult(
                title      = baslik,
                url        = adres,
                poster     = item.get("object_poster_url") or item.get("poster"),
                year       = str(yil) if yil else None,
                rating     = str(puan) if puan else None,
                media_type = "series" if dizi_mi else "movie",
            ))
        return sonuclar

    async def load_item(self, url: str) -> Union[MovieInfo, SeriesInfo]:
        html = await self.async_cf_get(url)
        soup = BeautifulSoup(html or "", "html.parser")

        poster_el = soup.select_one("div.page-top img[alt]")
        poster = self.fix_url(poster_el.get("src")) if poster_el and poster_el.get("src") else None
        if not poster:
            og = soup.select_one('meta[property="og:image"]')
            poster = og.get("content") if og else None

        yil = self._bilgi(soup, "Yıl")
        sure = self._bilgi(soup, "Süre")
        kategoriler = self._bilgi(soup, "Kategoriler")
        etiketler = [e for e in (kategoriler or "").split() if e]

        sure_dk = None
        if sure:
            m = re.search(r"(\d+)", sure)
            if m:
                sure_dk = int(m.group(1))

        ozet = None
        d = soup.select_one("div.summary p")
        if d:
            ozet = self._temizle(d.get_text(" "))
        if not ozet:
            og = soup.select_one('meta[property="og:description"]') or soup.select_one('meta[name="description"]')
            if og:
                ozet = self._temizle(og.get("content"))

        # ---- Dizi ----
        if "/series/" in url:
            baslik_el = soup.select_one("div.flex h2")
            baslik = self._temizle(baslik_el.get_text() if baslik_el else "")
            if not baslik:
                h1 = soup.select_one("h1")
                baslik = self._temizle(h1.get_text()) if h1 else ""

            bolumler: List[Episode] = []
            for kutu in soup.select("div.relative.w-full.flex.items-start.gap-4"):
                a = kutu.select_one("a[data-dizipal-pageloader]")
                if not a:
                    continue
                ad = a.get("href")
                h2 = a.select_one("h2")
                info = a.select_one("div.text-white.text-sm.opacity-80")
                isim = self._temizle(h2.get_text()) if h2 else ""
                info_metni = self._temizle(info.get_text()) if info else ""
                if not ad or not isim:
                    continue

                sezon = bolum = None
                m = re.search(r"(\d+)\.\s*Sezon", info_metni, re.I)
                if m:
                    sezon = int(m.group(1))
                m = re.search(r"(\d+)\.\s*Bölüm", info_metni, re.I)
                if m:
                    bolum = int(m.group(1))
                if sezon is None or bolum is None:
                    # "/bolum/<slug>-1x3" kalıbından
                    m2 = re.search(r"-(\d+)x(\d+)$", ad or "")
                    if m2:
                        sezon, bolum = int(m2.group(1)), int(m2.group(2))

                # Episode modeli "sezon/bölüm" içeren başlıkları siliyor
                temiz = re.sub(r"\s*\d+\s*[xX.]\s*\d+\s*$", "", isim).strip() or isim
                bolumler.append(Episode(url=self.fix_url(ad), title=temiz,
                                        season=sezon, episode=bolum))

            sezonlar: Dict[Any, List[Episode]] = {}
            for b in bolumler:
                sezonlar.setdefault(b.season if b.season is not None else 1, []).append(b)
            for liste in sezonlar.values():
                liste.sort(key=lambda b: (b.episode if b.episode is not None else 0))

            return SeriesInfo(
                content_type = "series",
                url          = url,
                title        = baslik or None,
                poster       = poster,
                description  = ozet,
                year         = yil,
                tags         = kategoriler or None,
                seasons      = sezonlar or None,
            )

        # ---- Film ----
        baslik_el = soup.select_one("h1")
        baslik = self._temizle(baslik_el.get_text() if baslik_el else "")
        # "ओह माय डॉग (Ohh My Dog)" -> parantez içindeki orijinal adı ayıklayıp temizle
        orijinal = None
        m = re.match(r"^(.*?)\s*\(([^()]+)\)\s*$", baslik)
        if m:
            orijinal, baslik = self._temizle(m.group(2)), self._temizle(m.group(1))

        if not baslik:
            og = soup.select_one('meta[property="og:title"]')
            baslik = self._temizle((og.get("content") or "").split("|")[0]) if og else ""

        return MovieInfo(
            content_type    = "movie",
            url             = url,
            title           = baslik or None,
            original_title  = orijinal,
            description     = ozet,
            poster_url      = poster,
            release_date    = yil,
            runtime_minutes = sure_dk or 0,
            genre           = etiketler,
            is_featured     = True,
        )

    # ================================================================== #
    # Oynatıcı
    # ================================================================== #

    def _iframe_coz(self, sifreli_metin: str) -> str:
        """PBKDF2 + AES ile iframe adresini çözer (Kotlin decryptDizipalData)."""
        ct = re.search(r'"ciphertext"\s*:\s*"([^"]+)"', sifreli_metin)
        iv = re.search(r'"iv"\s*:\s*"([^"]+)"', sifreli_metin)
        salt = re.search(r'"salt"\s*:\s*"([^"]+)"', sifreli_metin)
        if not (ct and iv and salt):
            return ""

        try:
            iv_b = bytes.fromhex(iv.group(1))
            salt_b = bytes.fromhex(salt.group(1))
            ct_b = base64.b64decode(ct.group(1))

            kdf = PBKDF2HMAC(algorithm=hashes.SHA512(), length=32,
                             salt=salt_b, iterations=999)
            anahtar = kdf.derive(IFRAME_PASSPHRASE.encode("utf-8"))

            cozucu = Cipher(algorithms.AES(anahtar), modes.CBC(iv_b)).decryptor()
            duz = cozucu.update(ct_b) + cozucu.finalize()
            geri = crypto_padding.PKCS7(128).unpadder()
            adres = (geri.update(duz) + geri.finalize()).decode("utf-8", "replace").replace("\\/", "/").strip()
        except Exception as e:
            print(f"[!] {self.name}: iframe çözme hatası: {e}")
            return ""

        if adres.startswith("://"):
            return f"https{adres}"
        if adres.startswith("//"):
            return f"https:{adres}"
        if not adres.startswith("http"):
            return f"https://{adres}"
        return adres

    async def load_links(self, url: str) -> List[str]:
        """Şifreli iframe adresini döner; çözüm ExtractorManager'a bırakılır.

        `dplayer82.site` host'u repodaki ContentX oynatıcısı (SNplayer) tarafından
        `openPlayer` → `source2.php` → `master.m3u8` adımına kadar çözülür.
        """
        html = await self.async_cf_get(url)
        soup = BeautifulSoup(html or "", "html.parser")

        sifreli = soup.select_one("div[data-rm-k=true]")
        metin = self._temizle(sifreli.get_text()) if sifreli else ""

        if metin:
            iframe = self._iframe_coz(metin)
        else:
            # Yedek: sayfadaki doğrudan iframe
            es = soup.select_one("iframe")
            iframe = self.fix_url(es.get("src")) if es and es.get("src") else ""

        if not iframe:
            print(f"[!] {self.name}: oynatıcı adresi bulunamadı ({url})")
            return []

        # Bazı oynatıcılar iframe içinde ikinci bir katman daha kullanıyor
        return [iframe]