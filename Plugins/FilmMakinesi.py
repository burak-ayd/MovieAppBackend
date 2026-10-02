# Oluşturan: Burak Aydoğan

import re
import urllib.parse

from typing import Any, Dict, List, Optional

from parsel import Selector

from Core.Plugin.PluginBase import PluginBase
from Core.Plugin.PluginModels import Episode, MovieInfo, MainPageResult, SearchResult, SeriesInfo


class FilmMakinesi(PluginBase):
    """FilmMakinesi kaynak site kazıyıcısı (film + dizi).

    Sayfa yapısı Kotlin ile aynı; `a.item` kartlarında zengin `data-*`
    attribute'ları bulunduğu için kartlar oradan besleniyor.
    """

    name = "FilmMakinesi"
    language = "tr"
    main_url = "https://filmmakinesi.to"
    favicon = f"https://www.google.com/s2/favicons?domain={main_url}&sz=256"
    description = "Film ve dizi izleme sitesi."

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Referer": f"{main_url}/",
    }

    # Kart rozetlerindeki ses/kalite göstergeleri
    _SES_ROZETLERI = ("dual", "dublaj", "altyaz")

    main_page = {
        "Son Filmler":   f"{main_url}/filmler-1/",
        "Son Diziler":   f"{main_url}/yabanci-dizi-izle-1/",
        "Aksiyon":       f"{main_url}/tur/aksiyon-fm1/film/",
        "Komedi":        f"{main_url}/tur/komedi-fm1/film/",
        "Korku":         f"{main_url}/tur/korku-fm2/film/",
        "Bilim Kurgu":  f"{main_url}/tur/bilim-kurgu-fm3/film/",
        "Gerilim":      f"{main_url}/tur/gerilim-fm1/film/",
        "Macera":        f"{main_url}/tur/macera-fm1/film/",
        "Fantastik":     f"{main_url}/tur/fantastik-fm1/film/",
    }

    # ================================================================== #
    # Yardımcılar
    # ================================================================== #

    def generate_slug(self, title: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
        return slug or str(id(title))

    def _sayfa(self, sayfa: int, url: str) -> str:
        if not url:
            return f"{self.main_url}/filmler-1/"
        if sayfa <= 1:
            return url
        govde = url.rstrip("/")
        return f"{govde}/sayfa/{sayfa}/"

    def _poster(self, kutu: Selector) -> Optional[str]:
        return self.fix_url(
            kutu.css(".thumbnail-outer img::attr(src)").get()
            or kutu.css(".thumbnail-outer img::attr(srcset)").get() or ""
        ) or None

    def _rozetleri_coz(self, kutular: Any) -> List[str]:
        """`div.item-info` içindeki ses/kalite rozetlerini okur.

        Yapı: `<div>HD</div><div>Dual</div><span class="rating">7.2</span><div>162</div>`
        Boş `div`'ler (ikon alanları) ve saf sayılar (yorum/rozet adedi) atlanır.
        Detay sayfalarında öneri listeleri de aynı rozetleri taşıdığı için
        yinelenenler de elenir.
        """
        rozetler: List[str] = []
        # Hem `a.item` kutularını hem de doğrudan `div.item-info` listesini kabul et
        info_kutulari = kutular if isinstance(kutular, list) else [kutular]
        for kutu in info_kutulari:
            for div in kutu.css("div.item-info div"):
                metin = (div.xpath("normalize-space(.)").get() or "").strip()
                if not metin or div.attrib.get("class") == "rating":
                    continue
                if metin.isdigit():
                    continue
                if metin not in rozetler:
                    rozetler.append(metin)
        return rozetler

    def _karti(self, kutu: Selector, category: str = "") -> Optional[MainPageResult]:
        """`a.item[data-title]` -> MainPageResult"""
        if not isinstance(kutu, Selector):
            return None

        adres = self.fix_url(kutu.attrib.get("href") or "")
        if not adres:
            return None

        baslik = (kutu.attrib.get("data-title") or "").strip()
        if not baslik:
            # Kategori menü bağlantıları `data-title` taşımıyor; içerik kartı değil
            return None

        tur = "series" if "/dizi/" in adres else "movie"

        rozetler = self._rozetleri_coz(kutu)
        sesler = [r for r in rozetler
                  if any(k in r.lower() for k in self._SES_ROZETLERI)]
        kaliteler = [r for r in rozetler if r not in sesler]

        etiket = ", ".join(sesler) or None

        puan = kutu.attrib.get("data-score")
        try:
            puan = f"{float(puan):.1f}" if puan not in (None, "") else None
        except (ValueError, TypeError):
            puan = None

        yil = None
        m = re.search(r"((?:19|20)\d{2})", adres)
        if m:
            yil = m.group(1)

        return MainPageResult(
            category=category or None,
            title=self.clean_title(baslik),
            url=adres,
            poster=self._poster(kutu),
            release_date=yil,
            rating=puan,
            language=etiket,
            description=f"{' | '.join(kaliteler)}" if kaliteler else None,
            media_type=tur,
            plugin=self.name,
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
                            or self.main_page["Son Filmler"])
        secici = await self._get(hedef)
        if not secici:
            return []

        sonuclar, gorulen = [], set()
        for kutu in secici.css("a.item"):
            kart = self._karti(kutu, category)
            if not kart or kart.url in gorulen:
                continue
            gorulen.add(kart.url)
            sonuclar.append(kart)
        return sonuclar

    async def search(self, query: str) -> List[SearchResult]:
        secici = await self._get(f"{self.main_url}/arama/?s={urllib.parse.quote_plus(query)}")
        if not secici:
            return []

        results, gorulen = [], set()
        for kutu in secici.css("a.item"):
            kart = self._karti(kutu)
            if not kart or kart.url in gorulen:
                continue
            gorulen.add(kart.url)
            results.append(SearchResult(
                title=kart.title,
                url=kart.url,
                poster=kart.poster,
                year=kart.release_date,
                rating=kart.rating,
                media_type=kart.media_type,
                plugin=self.name,
                metadata={
                    "language": kart.language,
                    "quality": kart.description,
                } if kart.language or kart.description else {},
            ))
        return results

    # ------------------------------------------------------------------ #
    # Detay
    # ------------------------------------------------------------------ #

    def _ortak_detay(self, secici: Selector, url: str) -> Dict[str, Any]:
        """Film ve dizi sayfalarının ortak alanlarını okur."""
        h1 = secici.css("h1.title")
        ham_baslik = (h1[0].xpath("normalize-space(.)").get() if h1 else "") or ""
        baslik = self.clean_title(re.sub(r"\s*izle\s*\(?\d{4}\)?\s*$", "", ham_baslik, flags=re.I))

        yil = None
        if h1:
            m = re.search(r"((?:19|20)\d{2})", ham_baslik)
            if m:
                yil = m.group(1)
        if not yil:
            m = secici.css("h1.title .date a::text").get()
            if m and re.fullmatch(r"\s*(19|20)\d{2}\s*", str(m)):
                yil = str(m).strip()

        puan = secici.css(".imdb b::text").get()
        try:
            puan = f"{float(puan):.1f}" if puan else None
        except (ValueError, TypeError):
            puan = None

        sure = None
        m = secici.css(".time::text").get()
        if m and re.search(r"\d+", m):
            try:
                sure = int(re.sub(r"\D", "", m))
            except ValueError:
                sure = None

        turler = [t.strip() for t in secici.css("#info--box .content .type a::text").getall()
                  if t.strip()]
        # Detay sayfasındaki rozetler: film -> "HD | Dual", dizi -> "Yabancı Dizi".
        # Sayfada öneri listeleri de aynı rozetleri taşıdığı için yalnızca
        # ilk `item-info` (ana içeriğinki) okunur.
        rozetler = self._rozetleri_coz(secici.css("div.item-info")[:1])
        sesler = [r for r in rozetler
                  if any(k in r.lower() for k in self._SES_ROZETLERI)]
        # Dizi rozetleri ("Yabancı Dizi", "Yerli Dizi") ses değil etiket olarak kalır
        diger = [r for r in rozetler if r not in sesler]
        etiket = ", ".join(sesler) or None

        # Özet `<p>` içinde; `clean_title` metin birleştirmediği için normalize kullanılıyor
        ozet_raw = secici.css(".info-description").xpath("normalize-space(.)").get() \
            or secici.css("#info--box .content p").xpath("normalize-space(.)").get() or ""
        ozet = self.clean_title(ozet_raw)
        yonetmen = self.clean_title(secici.css(".director a::text").get() or "")

        oyuncular = []
        for kutu in secici.css("#cast .cast"):
            isim = self.clean_title(kutu.css(".cast-name::text").get() or "")
            if isim:
                oyuncular.append(isim)

        # Fragman: `data-video_url` içinde YouTube bağlantısı olabilir
        fragman = None
        ham_fragman = secici.css(".trailer-button::attr(data-video_url)").get()
        if ham_fragman:
            ham_fragman = self.fix_url(ham_fragman.strip())
            if "youtube" in ham_fragman.lower():
                m = re.search(r"(?:embed/|watch\?v=)([\w-]{6,})", ham_fragman)
                # `MovieInfo.fragman_url` çıplak video ID bekliyor
                fragman = m.group(1) if m else None
            else:
                fragman = None
        if not fragman:
            m = re.search(r"(?:embed/|watch\?v=)([\w-]{6,})", str(secici.get()))
            if m and "youtube" in secici.get().lower():
                fragman = m.group(1)

        imdb_id = None
        m = re.search(r"imdb_id=(tt\d{7,9})", str(secici.get()))
        if m:
            imdb_id = m.group(1)
        else:
            m = re.search(r"tt\d{7,9}", secici.get())
            if m:
                imdb_id = m.group(0)

        poster = self.fix_url(secici.css("#info--box .cover img::attr(src)").get() or "")

        return {
            "baslik": baslik,
            "ham_baslik": ham_baslik,
            "yil": yil,
            "puan": puan,
            "sure": sure,
            "turler": turler,
            "ozet": ozet,
            "yonetmen": yonetmen or None,
            "oyuncular": oyuncular,
            "fragman": fragman,
            "imdb_id": imdb_id,
            "poster": poster,
            "ses": etiket,
            "rozetler": diger,
        }

    async def load_item(self, url: str) -> Optional[MovieInfo]:
        secici = await self._get(url)
        if not secici:
            return None

        if "/dizi/" in url:
            return await self._dizi_kur(url, secici)

        d = self._ortak_detay(secici, url)
        if not d["baslik"]:
            return None

        return MovieInfo(
            content_type="movie",
            url=url,
            title=d["baslik"],
            slug=self.generate_slug(d["baslik"]),
            description=d["ozet"] or None,
            poster_url=d["poster"] or None,
            fragman_url=d["fragman"],
            release_date=d["yil"],
            runtime_minutes=d["sure"] or 0,
            rating=d["puan"],
            genre=d["turler"],
            cast_members=d["oyuncular"],
            director=d["yonetmen"],
            imdb_id=d["imdb_id"],
            # "Dual" / "Dublaj" / "Altyazılı" rozetleri
            language=d["ses"],
            audio_languages=d["rozetler"] or None,
            plugin=self.name,
        )

    async def load_series(self, url: str) -> Optional[SeriesInfo]:
        secici = await self._get(url)
        if not secici:
            return None
        return await self._dizi_kur(url, secici)

    async def _dizi_kur(self, url: str, secici: Selector) -> Optional[SeriesInfo]:
        """Dizi detayı + sezon/bölüm listesi."""
        d = self._ortak_detay(secici, url)
        if not d["baslik"]:
            return None

        seasons_dict: Dict[str, List[Episode]] = {}
        for kutular in (secici.css("a.item-ep"),):
            for kutu in kutular:
                ep_url = self.fix_url(kutu.attrib.get("href") or "")
                if not ep_url:
                    continue

                baslik_metni = (kutu.css(".ep-title").xpath("normalize-space(.)").get() or "").strip()
                # Bölüm adı `<div class="ep-details"><span>Pilot</span></div>` içinde
                isim = (kutu.css(".ep-details").xpath("normalize-space(.)").get() or "").strip()

                m_s = re.search(r"(\d+)\s*\.\s*Sezon", baslik_metni, re.IGNORECASE)
                m_b = re.search(r"(\d+)\s*\.\s*Bölüm", baslik_metni, re.IGNORECASE)
                sezon_no = int(m_s.group(1)) if m_s else None
                bolum_no = int(m_b.group(1)) if m_b else None

                if sezon_no is None:
                    m = re.search(r"/sezon-(\d+)/", ep_url)
                    sezon_no = int(m.group(1)) if m else 1
                if bolum_no is None:
                    m = re.search(r"/bolum-(\d+)/", ep_url)
                    bolum_no = int(m.group(1)) if m else None
                if bolum_no is None:
                    continue

                baslik_ep = self.clean_title(isim) or f"{sezon_no}. Sezon {bolum_no}. Bölüm"
                episode_obj = Episode(
                    season=sezon_no,
                    episode=bolum_no,
                    season_number=sezon_no,
                    episode_number=bolum_no,
                    title=baslik_ep,
                    url=ep_url,
                )
                seasons_dict.setdefault(str(sezon_no), []).append(episode_obj)

        for liste in seasons_dict.values():
            liste.sort(key=lambda b: (b.episode or 0))

        tags = ", ".join(d["turler"]) if d["turler"] else None
        # Dizi sayfasında ses rozeti yok ("Yabancı Dizi" gibi etiketler var),
        # bu yüzden etiketler `tags` alanında birleştiriliyor.
        ek_etiket = [x for x in (d["ses"], *d["rozetler"]) if x]
        if ek_etiket:
            tags = ", ".join([tags, *ek_etiket]) if tags else ", ".join(ek_etiket)

        return SeriesInfo(
            content_type="series",
            url=url,
            title=d["baslik"],
            description=d["ozet"] or None,
            poster=d["poster"] or None,
            fragman_url=d["fragman"],
            year=d["yil"],
            rating=d["puan"],
            tags=tags,
            actors=", ".join(d["oyuncular"]) if d["oyuncular"] else None,
            plugin=self.name,
            seasons=seasons_dict if seasons_dict else None,
        )

    # ------------------------------------------------------------------ #
    # Oynatma
    # ------------------------------------------------------------------ #

    async def load_links(self, url: str) -> List[str]:
        """Oynatıcı embed adreslerini toplar (çözüm ExtractorManager'a bırakılır)."""
        if not url:
            return []

        secici = await self._get(url)
        if not secici:
            return []

        embedler: List[str] = []
        for kutu in secici.css(".video-parts a[data-video_url]"):
            adres = self.fix_url((kutu.attrib.get("data-video_url") or "").strip())
            if adres and adres not in embedler:
                embedler.append(adres)

        if not embedler:
            for iframe in secici.css(".after-player iframe"):
                ham = (iframe.attrib.get("data-src") or iframe.attrib.get("src") or "").strip()
                if not ham or "youtube" in ham.lower():
                    continue
                adres = self.fix_url(ham)
                if adres and adres not in embedler:
                    embedler.append(adres)

        return embedler

    def get_extraction_data(self, url: str) -> Optional[Dict[str, Any]]:
        """Oynatıcı sayfası için film sayfasını referer olarak verir."""
        return {"Referer": self.fix_url(url)}


if __name__ == "__main__":
    import asyncio
    import urllib.parse

    async def main():
        plugin = FilmMakinesi()
        test = await plugin.get_main_page(1)
        print(test[0] if test else "Sonuç yok")
        # await plugin.search("matrix")
        # print((await plugin.load_item("https://filmmakinesi.to/film/matrix-reloaded-izle-2003-fm3/")).model_dump_json(indent=4))
        # print(await plugin.load_links("https://filmmakinesi.to/film/matrix-reloaded-izle-2003-fm3/"))
        await plugin.close()

    asyncio.run(main())