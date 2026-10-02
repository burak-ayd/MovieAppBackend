# Oluşturan: Burak Aydoğan

import base64
import json
import re
import urllib.parse

from typing import Any, Dict, List, Optional

from parsel import Selector

from Core.Plugin.PluginBase import PluginBase
from Core.Plugin.PluginModels import MovieInfo, MainPageResult, SearchResult


class SinemaCX(PluginBase):
    """SinemaCX kaynak site kazıyıcısı (yalnızca filmler).

    Site yeniden tasarlandığı için kart seçicileri güncel DOM'a göre yazıldı:
      - Karusel (ana sayfa) : `a.own-carousel__item.slayt_kutu`
      - Liste sayfaları     : `div.film_kutusu > a`
      - Oynatıcı            : `iframe#video_playeriframe[data-vsrc]` (base64)
    """

    name = "SinemaCX"
    language = "tr"
    main_url = "https://sinemacc.com"
    favicon = f"https://www.google.com/s2/favicons?domain={main_url}&sz=256"
    description = "Güncel filmleri dublaj ve altyazılı izleyebileceğiniz film sitesi."

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Referer": f"{main_url}/",
    }

    # `player.filmizle.in` isteği için gerekli başlık
    player_headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{main_url}/",
    }

    main_page = {
        "Son Eklenen Filmler": f"{main_url}/page/SAYFA/",
        "Keşfet":              f"{main_url}/film-arsivi/",
        "Türkçe Dublaj":       f"{main_url}/dil/turkce-dublaj/",
        "Türkçe Altyazı":      f"{main_url}/dil/turkce-altyazi/",
        "Netflix":             f"{main_url}/kanal/netflix/",
        "Marvel":              f"{main_url}/kanal/marvel/",
        "İntikam Konusu":      f"{main_url}/konu/intikam-filmleri/",
        "Uzay Konusu":         f"{main_url}/konu/uzay-filmleri/",
        "Zombi Konusu":        f"{main_url}/konu/zombi-filmleri/",
        "Hindistan":           f"{main_url}/ulke/hindistan/",
        "2026 Filmleri":       f"{main_url}/yil/2026/",
    }

    # ================================================================== #
    # Yardımcılar
    # ================================================================== #

    def generate_slug(self, title: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
        return slug or str(id(title))

    def _sayfa(self, sayfa: int, url: str) -> str:
        """`.../page/SAYFA/` kalıbını gerçek sayfa numarasıyla değiştirir."""
        if not url:
            return f"{self.main_url}/page/1"
        if "SAYFA" in url:
            return url.replace("SAYFA", str(max(1, int(sayfa or 1))))
        if sayfa <= 1:
            return url
        govde = url.rstrip("/")
        return f"{govde}/page/{sayfa}/"

    @staticmethod
    def _temiz_sayi(metin: Optional[str], ondalik: bool = False) -> Optional[float]:
        """'113 Dakika' -> 113.0, '★ 4.7' -> 4.7 (ondalik=True ise ondalik korunur)"""
        if not metin:
            return None
        m = re.search(r"\d+(?:[.,]\d+)?", metin)
        if not m:
            return None
        try:
            return float(m.group(0).replace(",", ".")) if ondalik \
                else int(float(m.group(0).replace(",", ".")))
        except (ValueError, TypeError):
            return None

    def _poster(self, kutu: Selector) -> Optional[str]:
        """`img[data-src]` -> `img[src]` (src yer tutucu data-URI olduğu için önce data-src)"""
        return self.fix_url(
            kutu.css("img::attr(data-src)").get() or kutu.css("img::attr(src)").get() or ""
        ) or None

    @staticmethod
    def _ld_json(secici: Selector) -> Dict[str, Any]:
        """Sayfadaki `application/ld+json` bloğunu sözlüğe çevirir.

        Başlık, tam özet, IMDb puanı/oy sayısı, yönetmen ve tüm oyuncu listesi
        bu blokta; HTML'deki `span.imdb` etiketleri "ilgili filmler" listesine
        ait olduğu için güvenilmez.
        """
        for blok in secici.css("script[type='application/ld+json']"):
            ham = blok.get().strip()
            if ham.startswith("<"):
                ham = re.sub(r"</?script[^>]*>", "", ham).strip()
            try:
                veri = json.loads(ham)
            except (ValueError, TypeError):
                continue
            if isinstance(veri, list):
                veri = next((v for v in veri if isinstance(v, dict)
                             and v.get("@type") in ("Movie", "TVMovie")), {})
            if isinstance(veri, dict) and veri:
                return veri
        return {}

    def _kart(self, kutu: Selector, category: str = "") -> Optional[MainPageResult]:
        """Hem karusel (`a.own-carousel__item`) hem liste (`div.film_kutusu > a`) kartları."""
        if not isinstance(kutu, Selector):
            return None

        adres = self.fix_url(kutu.css("::attr(href)").get() or "")
        if not adres or "/film/" not in adres:
            return None

        # Yeni tema: span.title > span.text (+ span.orj) veya span.detay
        baslik = kutu.css("span.title span.text::text").get() or kutu.css("span.title::text").get()
        orijinal = kutu.css("span.title span.orj::text").get()
        if not baslik:
            # Eski tema: div.yanac span
            baslik = kutu.css("div.yanac span::text").get()
            orijinal = None
        if not baslik:
            baslik = (kutu.css("::attr(title)").get() or "").replace(" İzle", "").strip()

        if not baslik:
            return None

        puan = self._temiz_sayi(kutu.css("span.puan::text").get())
        yil = self._temiz_sayi(kutu.css("span.yil::text").get())
        sure = self._temiz_sayi(kutu.css("span.sure::text").get())

        return MainPageResult(
            category=category or None,
            title=self.clean_title(baslik),
            url=adres,
            poster=self._poster(kutu),
            release_date=str(yil) if yil else None,
            rating=str(puan) if puan else None,
            description=self.clean_title(orijinal) if orijinal else None,
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
        hedef = self._sayfa(page, url or self.main_page.get(category) or
                            f"{self.main_url}/page/1")
        secici = await self._get(hedef)
        if not secici:
            return []

        # Karusel kartları ve liste sayfalarındaki film kutularını birlikte topla
        kutular = (secici.css("a.own-carousel__item") +
                   secici.css("div.film_kutusu > a"))

        sonuclar = []
        gorulen = set()
        for kutu in kutular:
            kart = self._kart(kutu, category)
            if not kart or kart.url in gorulen:
                continue
            gorulen.add(kart.url)
            sonuclar.append(kart)
        return sonuclar

    async def search(self, query: str) -> List[SearchResult]:
        # NOT: `/?s=` çalışmıyor (ana sayfayı döndürüyor). Gerçek arama ucu
        # `/arama/?s=` — sitenin `sistem.js` içindeki `arama_adresi` değişkeninde.
        secici = await self._get(f"{self.main_url}/arama/?s={urllib.parse.quote_plus(query)}")
        if not secici:
            return []

        results = []
        for kutu in (secici.css("div.film_kutusu > a") + secici.css("a.own-carousel__item")):
            kart = self._kart(kutu)
            if not kart:
                continue
            results.append(SearchResult(
                title=kart.title,
                url=kart.url,
                poster=kart.poster,
                year=kart.release_date,
                rating=kart.rating,
                media_type="movie",
                plugin=self.name,
            ))
        return results

    async def load_item(self, url: str) -> Optional[MovieInfo]:
        secici = await self._get(url)
        if not secici:
            return None

        ld = self._ld_json(secici)

        # --- Başlık ---
        h1 = secici.css("div.f-bilgi h1") or secici.css("h1")
        baslik = self.clean_title(
            h1[0].xpath("normalize-space(.)").get().replace(" İzle", "") if h1 else ""
        )
        baslik = baslik or self.clean_title(str(ld.get("name") or ""))
        if not baslik:
            return None

        orijinal = None
        alternatif = ld.get("alternateName")
        if alternatif and self.clean_title(str(alternatif)) != baslik:
            orijinal = self.clean_title(str(alternatif))

        # --- Görseller ---
        # `og:image` arka plan olabiliyor; poster `..._f.webp` (f = film/kapak)
        og_gorsel = secici.css("meta[property='og:image']::attr(content)").get() or ""
        poster = og_gorsel
        arkaplan = None
        if re.search(r"_(?:f|fm)\.(?:webp|jpg|png)$", og_gorsel, re.I):
            poster = og_gorsel
        else:
            arkaplan = og_gorsel or None

        # --- Açıklama ---
        # og:description sadece "X (YIL) filmini ... izle" cümlesi; asıl özet ld+json'da
        ozet = self.clean_title(str(ld.get("description") or "")) \
            or self.clean_title(secici.css("meta[property='og:description']::attr(content)").get() or "")

        turler = [t.strip() for t in secici.css("a[href*='/tur/']::text").getall() if t.strip()]

        # --- ul.detay -> ["130 Dakika", "1080p", "Türkçe Dublaj", "ABD", "2012"] ---
        detaylar = [d.xpath("normalize-space(.)").get() or "" for d in secici.css("ul.detay li")]
        sure = yil = kalite = None
        for d in detaylar:
            if "dakika" in d.lower() or re.search(r"PT\d+M", d):
                sure = self._temiz_sayi(d) or self._temiz_sayi(re.search(r"PT(\d+)M", d).group(1)
                                                          if re.search(r"PT(\d+)M", d) else None)
            elif re.fullmatch(r"\s*(19|20)\d{2}\s*", d):
                yil = self._temiz_sayi(d)
            elif re.fullmatch(r"\s*(?:2160p|1440p|1080p|720p|480p|4k)\s*", d, re.I):
                kalite = d.strip()
        if not sure and ld.get("duration"):
            m = re.search(r"PT(\d+)M", str(ld["duration"]))
            sure = int(m.group(1)) if m else None
        if not yil and ld.get("dateCreated"):
            yil = self._temiz_sayi(str(ld["dateCreated"])[:4])

        # --- IMDb ---
        # Puan: ld+json aggregateRating güvenilir. Sayfadaki `span.imdb`
        # etiketleri "ilgili filmler" listesine ait olduğu için yanlış değer verir.
        puan = None
        oy_sayisi = None
        toplama = ld.get("aggregateRating") or {}
        if isinstance(toplama, dict):
            puan = self._temiz_sayi(str(toplama.get("ratingValue") or ""), ondalik=True)
            oy_sayisi = self._temiz_sayi(str(toplama.get("ratingCount") or ""))

        imdb_id = None
        imdb_baglanti = secici.css("a.imdb_link::attr(href)").get() \
            or next((h for h in secici.css("a::attr(href)").getall()
                     if "imdb.com/title" in h), None)
        if imdb_baglanti:
            m = re.search(r"(tt\d{7,9})", imdb_baglanti)
            imdb_id = m.group(1) if m else None

        # --- Oyuncu / Yönetmen ---
        # Sayfa yalnızca 1 yönetmen + 1 oyuncu gösteriyor; tam liste ld+json'da.
        oyuncular, yonetmen = [], None
        for kutu in secici.css("div.oyuncu_kutusu"):
            isim = self.clean_title(kutu.css("span.detail small::text").get() or "")
            rol = self.clean_title(kutu.css("span.detail b::text").get() or "")
            if not isim:
                continue
            if "Yönetmen" in rol:
                yonetmen = isim
            else:
                oyuncular.append(isim)

        if not yonetmen and isinstance(ld.get("director"), dict):
            yonetmen = self.clean_title(str(ld["director"].get("name") or "")) or None
        elif yonetmen is None and isinstance(ld.get("director"), str):
            yonetmen = self.clean_title(ld["director"]) or None

        ld_oyuncular = [self.clean_title(str(a.get("name") or ""))
                        for a in (ld.get("actor") or []) if isinstance(a, dict)]
        if len(ld_oyuncular) > len(oyuncular):
            oyuncular = ld_oyuncular

        # --- Dil ---
        # `a[href*='/dil/']` "Altyazı, Dublaj" gibi kalite etiketleri de veriyor;
        # gerçek dil `meta[name=dc.language]` içinde.
        dil = secici.css("meta[name='dc.language']::attr(content)").get() \
            or secici.css("html::attr(lang)").get()
        dil = (dil or "").strip() or None
        ses_dilleri = [d.strip() for d in secici.css("a[href*='/dil/']::text").getall()
                       if d.strip() and ("Altyazı" in d or "Dublaj" in d)]

        # --- Ülke ---
        # `a[href*='/ulke/']` tüm sayfada arandığında sidebar'daki "Bollywood"
        # gibi ilgisiz bağlantılar geliyor; gerçek ülke `ul.detay` içinde.
        ulke = None
        for d in secici.css("ul.detay li"):
            aday = [x.strip() for x in d.css("a[href*='/ulke/']::text").getall() if x.strip()]
            if aday:
                ulke = aday[0]
                break

        # --- Fragman ---
        # NOT: `MovieInfo.fragman_url` alanı çıplak YouTube video ID'si bekliyor
        # (model doğrudan `watch?v=` ön ekini ekliyor), tam adres değil.
        fragman = None
        for buton in secici.css("button.part_button"):
            if "Fragman" not in (buton.xpath("normalize-space(.)").get() or ""):
                continue
            ham_rel = buton.css("::attr(rel)").get() or ""
            try:
                cozulen = base64.b64decode(ham_rel).decode("utf-8")
            except Exception:
                cozulen = ham_rel
            if "youtube" in cozulen.lower():
                m = re.search(r"(?:embed/|watch\?v=|youtu\.be/)([\w-]{6,})", cozulen)
                if m:
                    fragman = m.group(1)
            else:
                fragman = self.fix_url(cozulen) or None
            break

        # --- Ana görsel (ld+json `image`) poster için daha iyi olabilir ---
        if not poster and ld.get("image"):
            poster = str(ld["image"])

        return MovieInfo(
            content_type="movie",
            url=url,
            title=baslik,
            original_title=orijinal,
            slug=self.generate_slug(baslik),
            description=ozet or None,
            poster_url=self.fix_url(poster) if poster else None,
            backdrop_url=self.fix_url(arkaplan) if arkaplan else None,
            fragman_url=fragman,
            release_date=str(yil) if yil else None,
            runtime_minutes=sure or 0,
            rating=str(puan) if puan else None,
            vote_count=oy_sayisi or 0,
            imdb_id=imdb_id,
            genre=turler,
            cast_members=oyuncular,
            director=yonetmen,
            country=ulke,
            language=dil,
            quality=kalite,
            audio_languages=ses_dilleri,
            plugin=self.name,
        )

    async def load_links(self, url: str) -> List[str]:
        """Oynatıcı zincirini çözer ve doğrudan m3u8 adresini döndürür.

        Zincir: film sayfası -> base64 `data-vsrc` -> player.filmizle.in ->
        `getVideo` POST -> securedLink (m3u8)
        """
        if not url:
            return []

        secici = await self._get(url)
        if not secici:
            return []

        # Kaynak butonları `rel` alanında base64 iframe adresi tutuyor
        # (`Türkçe Dublaj` = gerçek oynatıcı, `Fragman` = youtube).
        gercek = None
        for buton in secici.css("button.part_button"):
            rel = buton.css("::attr(rel)").get() or ""
            try:
                cozulen = base64.b64decode(rel).decode("utf-8")
            except Exception:
                cozulen = rel
            if cozulen.startswith("http") and "youtube" not in cozulen.lower():
                gercek = cozulen
                break

        ham = gercek or secici.css("iframe#video_playeriframe::attr(data-vsrc)").get()
        if not ham:
            # Yedek: herhangi bir iframe (data-vsrc önce, src'de about:blank var)
            ham = self.gomulu_adres(secici, "iframe")
        if not ham:
            print(f"[!] {self.name}: oynatıcı iframe bulunamadı.")
            return []

        ham = ham.split("?img=")[0]
        try:
            iframe = base64.b64decode(ham).decode("utf-8")
        except Exception:
            iframe = self.fix_url(ham)
        if not iframe.startswith("http"):
            iframe = self.fix_url(iframe)

        # Yalnızca fragman/trailer olan sayfalarda oynatıcı 2. sayfada olabilir
        if any(k in iframe.lower() for k in ("youtube", "fragman", "trailer")):
            yedek = []
            for buton in secici.css("button.part_button"):
                rel = buton.css("::attr(rel)").get() or ""
                try:
                    cozulen = base64.b64decode(rel).decode("utf-8")
                except Exception:
                    cozulen = rel
                if cozulen.startswith("http") and not any(
                        k in cozulen.lower() for k in ("youtube", "fragman", "trailer")):
                    yedek.append(cozulen)
            if not yedek:
                hamlar = secici.css("iframe::attr(data-vsrc)").getall()
                yedek = [y for y in hamlar
                         if not any(k in y.lower() for k in ("youtube", "fragman", "trailer"))]
            if not yedek:
                print(f"[!] {self.name}: sadece fragman mevcut, oynatıcı yok.")
                return []
            try:
                iframe = base64.b64decode(yedek[0].split("?img=")[0]).decode("utf-8")
            except Exception:
                iframe = self.fix_url(yedek[0].split("?img=")[0])

        # Altyazılar (isteğe bağlı, çözemezse devam)
        await self._altyazilari_ekle(iframe)

        if "player.filmizle.in" not in iframe.lower():
            # Başka bir oynatıcı: adresi olduğu gibi extractor zincirine bırak
            return [iframe]

        temiz = iframe.split("?")[0]
        video_hash = temiz.split("/")[-1]
        base = re.search(r"https?://([^/]+)", temiz)
        if not base:
            return []
        api = f"https://{base.group(1)}/player/index.php?data={video_hash}&do=getVideo"

        try:
            cevap = await self.httpx.post(api, headers=self.player_headers, timeout=30.0)
            if cevap.status_code != 200:
                print(f"[!] {self.name}: oynatıcı HTTP {cevap.status_code}")
                return []
            veri = cevap.json()
        except Exception as e:
            print(f"[!] {self.name} oynatıcı hatası: {e}")
            return []

        link = veri.get("securedLink") or veri.get("videoSource")
        return [self.fix_url(link)] if link else []

    async def _altyazilari_ekle(self, iframe: str) -> List[Dict[str, str]]:
        """`playerjsSubtitle` bloğundan altyazı adreslerini toplar (çözümlemesi zorunlu değil)."""
        try:
            istek = await self.httpx.get(iframe, headers={"Referer": f"{self.main_url}/"},
                                        follow_redirects=True, timeout=30.0)
            if istek.status_code != 200:
                return []
            blok = re.search(r'playerjsSubtitle\s*=\s*"(.+?)"', istek.text)
            if not blok:
                return []
            return [{"lang": d[0], "url": self.fix_url(d[1])}
                    for d in re.findall(r"\[(.*?)]\s*(https?://[^\s\",]+)", blok.group(1))]
        except Exception:
            return []

    def get_extraction_data(self, url: str) -> Optional[Dict[str, Any]]:
        """Extractor için ekstra veri sağlar (bu eklentide gerekmiyor)."""
        return None


if __name__ == "__main__":
    import asyncio

    async def main():
        plugin = SinemaCX()
        test = await plugin.get_main_page(1)
        print(test[0] if test else "Sonuç yok")
        # await plugin.search("bulvar")
        # print((await plugin.load_item("https://sinemacc.com/film/bulvar-boulevard-2026/")).model_dump_json(indent=4))
        # print(await plugin.load_links("https://sinemacc.com/film/bulvar-boulevard-2026/"))
        await plugin.close()

    asyncio.run(main())