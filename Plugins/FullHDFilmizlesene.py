# Bu araç @keyiflerolsun tarafından | @KekikAkademi için yazılmıştır.
# Python portu: Kekik-cloudstream / FullHDFilmizlesene.kt
#
# Kaynak yapı (canlı doğrulandı):
#   * Kategori/ana sayfa : `/filmizle/<kategori>` + sayfa numarası (ör. `.../1`)
#   * Arama              : `/arama/<kelime>`
#   * Detay              : `/film/<slug>/`
#   * Oynatıcı kaynağı   : sayfadaki `scx = {...};` → base64(rot13(url))
#
# Kotlin'deki 3 kategori URL'si (`-hdf-izle`, `-izle-1` gibi ekler) siteden
# kaldırıldığı için güncel kanonik adresler kullanıldı; bölüm listesi site
# menüsünden alındı (32 kategori).

import base64
import json
import re
from typing import Any, Dict, List, Optional

from Core.Plugin.PluginBase import PluginBase
from Core.Plugin.PluginModels import MainPageResult, MovieInfo, SearchResult


def _rot13(text: str) -> str:
    """Kotlin rtt(): ROT13 (a-z / A-Z)."""
    out = []
    for ch in text:
        if "a" <= ch <= "z":
            out.append(chr((ord(ch) - 97 + 13) % 26 + 97))
        elif "A" <= ch <= "Z":
            out.append(chr((ord(ch) - 65 + 13) % 26 + 65))
        else:
            out.append(ch)
    return "".join(out)


def _atob(text: str) -> str:
    """Kotlin atob(): Base64 çözme (hatalı girdide boş dize)."""
    try:
        return base64.b64decode(text + "=" * (-len(text) % 4)).decode("utf-8", "replace")
    except Exception:
        return ""


# (yol, görünen ad) — /filmizle/... listesi sitenin kendi menüsünden alındı.
# İlk satır ("Ana Sayfa") ana sayfa kökünü gösterir; sayfalama kökte çalışmaz.
_KATEGORILER: tuple = (
    ("",                                          "Son Eklenenler"),
    ("/en-cok-izlenen-filmler",                    "En Çok izlenen Filmler"),
    ("/filmizle/imdb-puani-yuksek-filmler",        "IMDB Puanı Yüksek Filmler"),
    ("/filmizle/aile-filmleri",                    "Aile Filmleri"),
    ("/filmizle/aksiyon-filmleri",                 "Aksiyon Filmleri"),
    ("/filmizle/animasyon-filmleri",               "Animasyon Filmleri"),
    ("/filmizle/belgesel-filmleri",                "Belgeseller"),
    ("/filmizle/bilim-kurgu-filmleri",            "Bilim Kurgu Filmleri"),
    ("/filmizle/bluray-filmler",                   "Blu Ray Filmler"),
    ("/filmizle/cizgi-filmler",                    "Çizgi Filmler"),
    ("/filmizle/dram-filmler-izle",                "Dram Filmleri"),
    ("/filmizle/fantastik-filmler",                "Fantastik Filmler"),
    ("/filmizle/gerilim-filmleri",                 "Gerilim Filmleri"),
    ("/filmizle/gizem-filmleri",                   "Gizem Filmleri"),
    ("/filmizle/hint-filmleri",                    "Hint Filmleri"),
    ("/filmizle/komedi-filmleri",                  "Komedi Filmleri"),
    ("/filmizle/korku-filmleri",                   "Korku Filmleri"),
    ("/filmizle/macera-filmleri-izle",             "Macera Filmleri"),
    ("/filmizle/muzikal-filmler",                  "Müzikal Filmler"),
    ("/filmizle/polisiye-filmleri",                "Polisiye Filmleri"),
    ("/filmizle/psikolojik-filmler",               "Psikolojik Filmler"),
    ("/filmizle/romantik-filmler",                 "Romantik Filmler"),
    ("/filmizle/savas-filmleri",                   "Savaş Filmleri"),
    ("/filmizle/suc-filmleri",                     "Suç Filmleri"),
    ("/filmizle/tarih-filmleri",                   "Tarih Filmleri"),
    ("/filmizle/western-filmler",                  "Western Filmler"),
    ("/filmizle/yerli-filmler",                    "Yerli Filmler"),
    ("/filmizle/4k-filmler",                       "4K Filmler"),
    ("/filmizle/1080p-filmler-2",                  "1080p Filmler"),
    ("/filmizle/dual-filmler-1",                   "Dual Filmler"),
    ("/filmizle/turkce-altyazili-filmler-1",       "Türkçe Altyazılı Filmler"),
    ("/filmizle/turkce-dublaj-filmler-1",          "Türkçe Dublaj Filmler"),
    ("/filmizle/yabanci-filmler",                  "Yabancı Filmler"),
)


def kategori_sayfasi(main_url: str) -> Dict[str, str]:
    """Ana sayfa sözlüğü: ad -> hedef.

    Boş yol (`Ana Sayfa`) doğrudan kök adresi verir; diğerleri sayfa numarasıyla
    biter (`…/aile-filmleri/1`) ve `get_main_page` sondaki numarayı değiştirir.
    """
    sayfalar: Dict[str, str] = {}
    for yol, ad in _KATEGORILER:
        sayfalar[ad] = main_url.rstrip("/") if not yol else f"{main_url}{yol}/1"
    return sayfalar


class FullHDFilmizlesene(PluginBase):

    name        = "FullHDFilmizlesene"
    language    = "tr"
    main_url    = "https://www.fullhdfilmizlesene.now"
    description = "FullHDFilmizlesene - Full HD film izleme sitesi"
    favicon = f"https://www.google.com/s2/favicons?domain={main_url}&sz=256"

# Ekran görüntüsünde her kategori 18 film dönüyor; sayfa sonu bu sayıda bitiyor.
    sayfa_boyutu = 18

    def _kategori_url(self, yol: str, page: int = 1) -> str:
        """Kategori adresi + sayfa numarası (Kotlin: ``${request.data}${page}``)."""
        return f"{self.main_url}{yol}/{page}"

    # `main_page` property olamaz: PluginBase.url_update() `self.main_page` ataması yapar.
    # Ana sayfa (kök) sayfalanmaz; sitenin sayfalanan "yeni filmler" listesi
    # `/yeni-filmler/{sayfa}` biçiminde çalışır ve kökten farklı içerik verir.
    ana_sayfa_yolu = "/yeni-filmler"

    main_page: Dict[str, str] = kategori_sayfasi(main_url)

    # ================================================================== #
    # Yardımcılar
    # ================================================================== #

    def _temizle(self, deger: Optional[str]) -> str:
        metin = (deger or "").strip()
        return re.sub(r"\s+", " ", metin).strip()

    def _film_bloklari(self, html: str) -> List[str]:
        return re.findall(r'<li class="film".*?</li>', html, re.S)

    def _bloktan_kart(self, blok: str, kategori: str = "") -> Optional[MainPageResult]:
        """Kotlin ``Element.toSearchResult()``."""
        baslik = self._temizle(
            (re.search(r'class="film-title"[^>]*>(.*?)</', blok, re.S) or [None, ""])[1]
        )
        if not baslik:
            return None

        href = (re.search(r'<a[^>]+href="([^"]+)"', blok) or [None, ""])[1]
        if not href:
            return None

        poster = (re.search(r'data-src="([^"]+)"', blok) or [None, ""])[1] or None
        yil = self._yil_bul(blok)

        return MainPageResult(
            title        = baslik,
            url          = self.fix_url(href),
            category     = kategori,
            poster       = poster,
            release_date = str(yil) if yil else None,
        )

    def _yil_bul(self, html: str) -> Optional[int]:
        """Yıl: `/yil/<yil>` bağlantısından ya da 4 haneli sayıdan."""
        m = re.search(r'href="[^"]*?/yil/(?:[^"]*?-)(\d{4})', html)
        if not m:
            m = re.search(r'>(\d{4})\s*(?:Filmleri|filmleri)?\s*<', html)
        if m:
            try:
                yil = int(m.group(1))
            except ValueError:
                return None
            return yil if 1900 <= yil <= 2100 else None
        return None

    def _bilgi_satiri(self, html: str, etiket: str) -> Optional[str]:
        """`film-info` içindeki `<span class="dt">Etiket</span>` satırının `dd` içeriği."""
        m = re.search(
            r'<span class="dt">\s*' + re.escape(etiket) + r'\s*</span>\s*<div class="dd">(.*?)</div>',
            html, re.S)
        return self._temizle(re.sub(r"<[^>]+>", " ", m.group(1))) if m else None

    def _json_ld(self, html: str) -> dict:
        """Sayfadaki JSON-LD Movie bloğu (puan / oy sayısı burada)."""
        for blok in re.findall(
                r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S):
            try:
                veri = json.loads(blok.strip())
            except Exception:
                continue
            if isinstance(veri, dict):
                return veri
            if isinstance(veri, list):
                for aday in veri:
                    if isinstance(aday, dict):
                        return aday
        return {}

    # ================================================================== #
    # Zorunlu metotlar
    # ================================================================== #

    async def get_main_page(self, page: int, url: str = "", category: str = "") -> List[MainPageResult]:
        """Kotlin getMainPage: `${request.data}${page}`.

        * `Ana Sayfa` (kök adres): sayfalanmaz; sitenin `/yeni-filmler/{page}`
          listesi kullanılır.
        * Kategori adresleri: sondaki sayfa numarası istenen sayfayla değiştirilir.
        """
        kok = self.main_url.rstrip("/")
        hedef = (url or "").strip().rstrip("/")

        if not hedef or hedef == kok:
            hedef = f"{kok}{self.ana_sayfa_yolu}/{page}"
        else:
            hedef = f"{re.sub(r'/\d+$', '', hedef)}/{page}"

        html = await self.async_cf_get(hedef)
        kartlar = [self._bloktan_kart(b, category) for b in self._film_bloklari(html)]
        return [k for k in kartlar if k]

    async def search(self, query: str) -> List[SearchResult]:
        html = await self.async_cf_get(f"{self.main_url}/arama/{query.strip()}")
        kartlar = [self._bloktan_kart(b) for b in self._film_bloklari(html)]
        return [
            SearchResult(title=k.title, url=k.url, poster=k.poster, year=k.release_date, media_type="Film")
            for k in kartlar if k
        ]

    async def load_item(self, url: str) -> MovieInfo:
        html = await self.async_cf_get(url)

        # Başlık: `div.izle-titles > h1` (h2 orijinal ad)
        baslik = self._temizle(re.sub(r"<[^>]+>", " ",
            (re.search(r'class="izle-titles".*?<h1[^>]*>(.*?)</h1>', html, re.S) or [None, ""])[1]))
        if not baslik:
            baslik = self._temizle(re.sub(r"<[^>]+>", " ",
                (re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S) or [None, ""])[1]))

        orijinal = self._temizle(
            (re.search(r'class="izle-titles".*?<h2[^>]*>(.*?)</h2>', html, re.S) or [None, ""])[1]
        )

        poster = (re.search(r'data-src="([^"]*/poster/[^"]+)"', html) or [None, ""])[1] or None
        arkaplan = (re.search(r'data-src="([^"]*/cover/[^"]+)"', html) or [None, ""])[1] or None

        yil = self._yil_bul(html)

        # Özet
        ozet = self._temizle(
            (re.search(r'class="ozet-ic"[^>]*>\s*<p[^>]*>(.*?)</p>', html, re.S) or [None, ""])[1]
        )
        if not ozet:
            ozet = self._temizle(
                (re.search(r'itemprop="description"[^>]*>(.*?)</', html, re.S) or [None, ""])[1]
            )

        # Süre: "103 dk"
        sure = self._temizle((re.search(r'class="sure"[^>]*>\s*([^<]+)', html) or [None, ""])[1])
        sure_dk = None
        m = re.search(r"(\d+)", sure)
        if m:
            sure_dk = int(m.group(1))

        # Türler
        tur = self._bilgi_satiri(html, "Tür") or ""
        etiketler = [e.strip() for e in re.split(r"[,/–-]", tur) if e.strip()]
        if not etiketler:
            etiketler = [
                self._temizle(re.sub(r"<[^>]+>", " ", x))
                for x in re.findall(r'rel="category tag"[^>]*>(.*?)</a>', html, re.S)
            ]
        etiketler = [e for e in etiketler if e]

        # Oyuncular
        oyuncular_satir = self._bilgi_satiri(html, "Oyuncular") or ""
        oyuncular = [o.strip() for o in oyuncular_satir.split(",") if o.strip()]

        yonetmen = self._bilgi_satiri(html, "Yönetmen") or None

        # Fragman (sayfada varsa)
        fragman = (re.search(r'embedUrl":\s*"(.*?)"', html) or [None, ""])[1] or None

        # Benzer filmler: "Benzer Filmler" başlığından sonraki `li.film`
        benzer: List[MainPageResult] = []
        m = re.search(r'Benzer[^<"]{0,30}.{0,3000}?</ul>', html, re.S)
        if m:
            for blok in self._film_bloklari(m.group(0)):
                kart = self._bloktan_kart(blok)
                if kart:
                    benzer.append(kart)

        # Puan JSON-LD aggregateRating içinde; yoksa sayfadaki starCntx değişkeni
        ld = self._json_ld(html)
        toplam = ld.get("aggregateRating") or {}
        puan = toplam.get("ratingValue")
        oy_sayisi = toplam.get("ratingCount")
        if puan is None:
            m = re.search(r"var\s+starCntx\s*=\s*'([\d.,]+)'", html)
            puan = m.group(1) if m else None
        if oy_sayisi is None:
            m = re.search(r"var\s+starCnt\s*=\s*'([\d.,]+)'", html)
            oy_sayisi = m.group(1) if m else None

        try:
            oy_sayisi = int(oy_sayisi) if oy_sayisi is not None else 0
        except (TypeError, ValueError):
            oy_sayisi = 0

        return MovieInfo(
            content_type    = "movie",
            url             = url,
            title           = baslik or None,
            original_title  = orijinal or None,
            description     = ozet or None,
            poster_url      = poster,
            backdrop_url    = arkaplan,
            release_date    = str(yil) if yil else None,
            runtime_minutes = sure_dk or 0,
            rating          = str(puan) if puan is not None else None,
            vote_count      = oy_sayisi,
            genre           = etiketler,
            cast_members    = oyuncular,
            director        = yonetmen,
            fragman_url     = fragman,
            is_featured     = bool(benzer),
        )

    async def load_links(self, url: str) -> List[str]:
        """Kotlin loadLinks(): `scx` → rot13+base64 → oynatıcı adresleri.

        turbo.imgz.me adresleri extractor'ın beklediği ``anahtar||adres`` biçiminde
        verilir (bkz. Kotlin loadLinks).
        """
        html = await self.async_cf_get(url)

        m = re.search(r"scx\s*=\s*(\{.*?\});", html, re.S)
        if not m:
            return []

        try:
            scx: Dict[str, Any] = json.loads(m.group(1))
        except json.JSONDecodeError as e:
            print(f"[!] {self.name} scx JSON çözülemedi: {e}")
            return []

        linkler: List[str] = []
        for anahtar in ("atom", "advid", "advidprox", "proton", "fast", "fastly", "tr", "en"):
            kutu = scx.get(anahtar)
            if not isinstance(kutu, dict):
                continue

            t = (kutu.get("sx") or {}).get("t")

            if isinstance(t, list):
                cozulen = [_atob(_rot13(x)) for x in t if isinstance(x, str)]
            elif isinstance(t, dict):
                cozulen = [_atob(_rot13(v)) for v in t.values() if isinstance(v, str)]
            else:
                continue

            for adres in cozulen:
                adres = (adres or "").strip()
                if not adres:
                    continue
                linkler.append(f"{anahtar}||{adres}" if "turbo.imgz.me" in adres else adres)

        # yinelenenleri koru, sırayı koru
        return list(dict.fromkeys(linkler))

    # `is_featured` alanı öneri listesini taşımak için kullanılıyor; önerileri
    # saklamak isteyen istemciler `load_item` içindeki `benzer` listesini görebilir.