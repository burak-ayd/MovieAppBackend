# Oluşturan: Burak Aydoğan

import re
import urllib.parse

from typing import Any, Dict, List, Optional

from parsel import Selector

from Core.Helpers.EmbedHelper import EmbedHelper
from Core.Plugin.PluginBase import PluginBase
from Core.Plugin.PluginModels import MovieInfo, MainPageResult, SearchResult


class FilmModu(PluginBase):
    """FilmModu kaynak site kazıyıcısı (yalnızca filmler).

    Site güncellendiği için yollar değişti:
      - Kategori : `/hd-film-kategori/*` -> `/film-tur/*`
      - Detay    : `div.titles h1/h2` -> `[itemprop=name]/[itemprop=alternateName]`
      - Kaynak   : `div.alternates a` -> aynı, ancak `videoType` yalnızca
                   `-altyazili-` kaynak sayfasında dolu (ana sayfa `''`).
    """

    name = "FilmModu"
    language = "tr"
    main_url = "https://www.filmmodu.one"
    favicon = f"https://www.google.com/s2/favicons?domain={main_url}&sz=256"
    description = "Türkçe altyazılı film izleme sitesi."

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Referer": f"{main_url}/",
    }

    main_page = {
        # Kategori listesi sitenin menüsünden alındı (Kotlin'deki
        # `/hd-film-kategori/*` yolları artık 404 dönüyor).
        "Aksiyon":              f"{main_url}/film-tur/aksiyon",
        "Komedi":               f"{main_url}/film-tur/hd-komedi-filmleri",
        "Korku":                f"{main_url}/film-tur/korku-filmleri",
        "Bilim Kurgu":         f"{main_url}/film-tur/bilim-kurgu-filmleri",
        "Dram":                 f"{main_url}/film-tur/dram-filmleri",
        "Gerilim":             f"{main_url}/film-tur/gerilim",
        "Gizem":                f"{main_url}/film-tur/gizem-filmleri",
        "Fantastik":            f"{main_url}/film-tur/fantastik-filmler",
        "Macera":               f"{main_url}/film-tur/macera-filmleri",
        "Romantik":             f"{main_url}/film-tur/romantik-filmler",
        "Animasyon":            f"{main_url}/film-tur/animasyon",
        "Belgesel":             f"{main_url}/film-tur/belgeseller",
        "Tarih":                f"{main_url}/film-tur/tarih",
        "Savaş":                f"{main_url}/film-tur/savas-filmleri",
        "Suç":                  f"{main_url}/film-tur/suc-filmleri",
        "Müzik":                f"{main_url}/film-tur/muzik",
        "Aile":                 f"{main_url}/film-tur/aile-filmleri",
        "Hint Filmleri":        f"{main_url}/film-tur/hd-hint-filmleri",
        "Kült Filmler":         f"{main_url}/film-tur/kult-filmler-izle",
        "Kısa Film":            f"{main_url}/film-tur/kisa-film",
        "Stand Up":             f"{main_url}/film-tur/stand-up",
        "Tavsiye Filmler":      f"{main_url}/film-tur/tavsiye-filmler",
        "TV Film":              f"{main_url}/film-tur/tv-film",
        "Vahşi Batı":           f"{main_url}/film-tur/vahsi-bati-filmleri",
        "4K":                   f"{main_url}/film-tur/4k-film-izle",
        "Oscar Ödüllü":         f"{main_url}/film-tur/odullu-filmler-izle",
    }

    # ================================================================== #
    # Yardımcılar
    # ================================================================== #

    def generate_slug(self, title: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
        return slug or str(id(title))

    def _sayfa(self, sayfa: int, url: str) -> str:
        if not url:
            return f"{self.main_url}/film-tur/aksiyon?page=1"
        if sayfa <= 1:
            return url
        ayirici = "&" if "?" in url else "?"
        return f"{url}{ayirici}page={sayfa}"

    @staticmethod
    def _yil(metin: Optional[str]) -> Optional[str]:
        """'2005' / '2005-01-01' -> '2005'"""
        if not metin:
            return None
        m = re.search(r"((?:19|20)\d{2})", str(metin))
        return m.group(1) if m else None

    @staticmethod
    def _sure(metin: Optional[str]) -> Optional[int]:
        """'99 dk' / '100 dakika' -> 99 / 100"""
        if not metin:
            return None
        m = re.search(r"(\d+)\s*(?:dk|dakika|min)", str(metin), re.IGNORECASE)
        return int(m.group(1)) if m else None

    def _poster(self, kutu: Selector) -> Optional[str]:
        """`source[data-srcset]` -> `img[data-src]` -> `img[src]`"""
        return self.fix_url(
            kutu.css("source::attr(data-srcset)").get()
            or kutu.css("img::attr(data-src)").get()
            or kutu.css("img::attr(src)").get() or ""
        ) or None

    def _kart(self, kutu: Selector, category: str = "") -> Optional[MainPageResult]:
        """`div.movie` -> MainPageResult"""
        if not isinstance(kutu, Selector):
            return None

        adres = self.fix_url(kutu.css("a::attr(href)").get() or "")
        if not adres:
            return None

        baslik = kutu.css("a::text").get()
        if not baslik:
            baslik = (kutu.css("img::attr(alt)").get() or "").strip()
        if not baslik:
            return None

        diller = [d.strip().upper() for d in kutu.css("p.language span::attr(class)").getall()
                  if "flag" in d]
        etiket = " / ".join(sorted(set(diller))) or None

        return MainPageResult(
            category=category or None,
            title=self.clean_title(baslik),
            url=adres,
            poster=self._poster(kutu),
            language=etiket,
            plugin=self.name,
            media_type="movie",
        )

    async def _get(self, url: str) -> Optional[Selector]:
        try:
            istek = await self.httpx.get(url, headers=self.headers,
                                        follow_redirects=True, timeout=30.0)
        except Exception as e:
            print(f"[!] {self.name} istek hatası ({url}): {e}")
            return None

        if istek.status_code != 200:
            print(f"[!] {self.name}: HTTP {istek.status_code} ({url})")
            return None
        return Selector(istek.text)

    # ================================================================== #
    # Zorunlu metotlar
    # ================================================================== #

    async def get_main_page(self, page: int = 1, url: str = "", category: str = "") -> List[MainPageResult]:
        hedef = self._sayfa(page, url or self.main_page.get(category)
                            or self.main_page["Aksiyon"])
        secici = await self._get(hedef)
        if not secici:
            return []

        sonuclar, gorulen = [], set()
        for kutu in secici.css("div.movie"):
            kart = self._kart(kutu, category)
            if not kart or kart.url in gorulen:
                continue
            gorulen.add(kart.url)
            sonuclar.append(kart)
        return sonuclar

    async def search(self, query: str) -> List[SearchResult]:
        secici = await self._get(f"{self.main_url}/film-ara?term={urllib.parse.quote_plus(query)}")
        if not secici:
            return []

        results, gorulen = [], set()
        for kutu in secici.css("div.movie"):
            kart = self._kart(kutu)
            if not kart or kart.url in gorulen:
                continue
            gorulen.add(kart.url)
            results.append(SearchResult(
                title=kart.title,
                url=kart.url,
                poster=kart.poster,
                language=kart.language,
                media_type="movie",
                plugin=self.name,
            ))
        return results

    async def load_item(self, url: str) -> Optional[MovieInfo]:
        secici = await self._get(url)
        if not secici:
            return None

        baslik = self.clean_title(secici.css("h1[itemprop='name']::text").get()
                                  or secici.css("div.titles h1::text").get() or "")
        if not baslik:
            return None
        orijinal = self.clean_title(
            secici.css("h2[itemprop='alternateName']::text").get()
            or secici.css("div.titles h2::text").get() or "")

        poster = secici.css("meta[property='og:image']::attr(content)").get() \
            or secici.css("[itemprop='image']::attr(src)").get() \
            or secici.css("img.img-responsive::attr(src)").get()

        ozet = self.clean_title(
            secici.css("p[itemprop='description']::text").get()
            or secici.css("meta[property='og:description']::attr(content)").get() or "")

        yil = secici.css("span[itemprop='dateCreated']::text").get()
        yil = self._yil(yil)

        turler = [t.strip() for t in secici.css(
            "div.description a[href*='tur/']::text, "
            "div.description a[href*='kategori']::text").getall() if t.strip()]

        oyuncular = [self.clean_title(a.xpath("normalize-space(.)").get() or "")
                     for a in secici.css("[itemprop='actor']")]
        oyuncular = [o for o in oyuncular if o]

        # Yönetmen `itemprop="director"` işaretli <a> içinde (iç içe etiket),
        # bu yüzden metin doğrudan alınamıyor.
        yonetmen = None
        for d in secici.css("[itemprop='director']"):
            aday = self.clean_title(d.xpath("normalize-space(.)").get() or "")
            if not aday:
                aday = self.clean_title(d.css("::attr(title)").get() or "")
            aday = re.sub(r"\s*filmleri\s*$", "", aday).strip()
            if aday:
                yonetmen = aday
                break

        sure = self._sure(secici.get())

        # Fragman: yalnızca ana (Fragman) sayfasında iframe bulunur
        # Lazy-load koruması: src="about:blank" ihtimaline karşı data-src önce bakılır
        fragman = self.gomulu_adres(secici, "iframe")
        if fragman and "youtube" in fragman.lower():
            m = re.search(r"(?:embed/|watch\?v=)([\w-]{6,})", fragman)
            # `MovieInfo.fragman_url` çıplak YouTube video ID'si bekliyor
            fragman = m.group(1) if m else None
        else:
            fragman = None

        imdb_id = None
        m = re.search(r"tt\d{7,9}", secici.get())
        if m:
            imdb_id = m.group(0)

        return MovieInfo(
            content_type="movie",
            url=url,
            title=baslik,
            original_title=orijinal or None,
            slug=self.generate_slug(baslik),
            description=ozet or None,
            poster_url=self.fix_url(poster) if poster else None,
            fragman_url=fragman,
            release_date=yil,
            runtime_minutes=sure or 0,
            genre=turler,
            cast_members=oyuncular,
            director=yonetmen,
            imdb_id=imdb_id,
            plugin=self.name,
        )

    async def load_links(self, url: str) -> List[str]:
        """Kaynak zincirini çözer:
        film sayfası -> `div.alternates a` -> her kaynak sayfası ->
        `videoId`/`videoType` -> `/get-source` -> m3u8 + altyazı
        """
        if not url:
            return []

        secici = await self._get(url)
        if not secici:
            return []

        linkler: List[str] = []
        gorulen = set()

        for kaynak in secici.css("div.alternates a"):
            etiket = (kaynak.xpath("normalize-space(.)").get() or "").strip()
            adres = self.fix_url(kaynak.css("::attr(href)").get() or "")
            if not adres or etiket == "Fragman":
                continue
            if adres in gorulen:
                continue
            gorulen.add(adres)

            # NOT: Bazı filmlerde tek kaynak vardır ve buton kendi sayfasına
            # (`-altyazili-`) işaret eder. Bu durumda `url` atlanmamalıdır;
            # `videoType` yalnızca bu sayfalarda doludur.
            cozulen = await self._kaynak_coz(adres)
            if not cozulen and adres != url:
                cozulen = await self._kaynak_coz(url)

            for m3u8 in cozulen:
                if m3u8 not in linkler:
                    linkler.append(m3u8)

        return linkler

    async def _kaynak_coz(self, adres: str) -> List[str]:
        """Tek bir kaynak sayfasını çözer.

        Ana (Fragman) sayfasında `videoType` boş olduğu için yalnızca gerçek
        kaynak sayfalarında (`-altyazili-` gibi) sonuç verir.
        """
        try:
            istek = await self.httpx.get(adres, headers=self.headers,
                                        follow_redirects=True, timeout=30.0)
        except Exception as e:
            print(f"[!] {self.name} kaynak sayfası hatası ({adres}): {e}")
            return []

        if istek.status_code != 200:
            return []

        ham = istek.text
        m_id = re.search(r"videoId\s*=\s*'([^']*)'", ham)
        m_tip = re.search(r"videoType\s*=\s*'([^']*)'", ham)
        if not m_id or not m_id.group(1):
            return []

        video_id = m_id.group(1)
        video_tip = m_tip.group(1) if m_tip else ""

        api = f"{self.main_url}/get-source?movie_id={video_id}&type={video_tip}"
        try:
            cevap = await self.httpx.get(api, headers=self.headers,
                                        follow_redirects=True, timeout=30.0)
            if cevap.status_code != 200:
                return []
            veri = cevap.json()
        except Exception as e:
            print(f"[!] {self.name} get-source hatası ({adres}): {e}")
            return []

        sonuclar = []
        for kaynak in (veri.get("sources") or []):
            # API yanıtı olsa da aynı koruma: yer tutucu/şema adresleri elenir
            src = self.fix_url(EmbedHelper.en_iyi(kaynak.get("src"), kaynak.get("data-src")) or "")
            if src:
                sonuclar.append(src)
        return sonuclar

    def get_extraction_data(self, url: str) -> Optional[Dict[str, Any]]:
        """Extractor için ekstra veri sağlar (bu eklentide gerekmiyor)."""
        return None


if __name__ == "__main__":
    import asyncio

    async def main():
        plugin = FilmModu()
        test = await plugin.get_main_page(1)
        print(test[0] if test else "Sonuç yok")
        # await plugin.search("matrix")
        # print((await plugin.load_item("https://www.filmmodu.one/the-marksman-altyazili-film-izle")).model_dump_json(indent=4))
        # print(await plugin.load_links("https://www.filmmodu.one/the-marksman-altyazili-film-izle"))
        await plugin.close()

    asyncio.run(main())