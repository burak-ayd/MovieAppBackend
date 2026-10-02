import asyncio

import re

from typing import Any, Dict, List, Optional

from parsel import Selector

from Core.Plugin.PluginBase import PluginBase
from Core.Plugin.PluginModels import SearchResult, MainPageResult, SeriesInfo, Episode


class DiziMom(PluginBase):
    """DiziMom kaynak site kazıyıcısı (yalnızca diziler)."""

    name = "DiziMom"
    language = "tr"
    main_url = "https://www.dizimom.wiki"
    favicon = f"https://www.google.com/s2/favicons?domain={main_url}&sz=256"
    description = "Türkiye'nin en güncel dizi izleme sitesi"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "*/*",
        "Referer": f"{main_url}/",
    }

    # Oynatıcı sayfası mobil kullanıcı adı ve oturum açma bekliyor
    player_headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Mobile Safari/537.36",
    }

    # (yol, görünen ad) — Kotlin mainPageOf listesi
    _KATEGORILER = (
        ("/tum-bolumler/page/",           "Son Bölümler"),
        ("/yerli-dizi-izle/page/",        "Yerli Diziler"),
        ("/yabanci-dizi-izle/page/",      "Yabancı Diziler"),
        ("/tv-programlari-izle/page/",    "TV Programları"),
        ("/netflix-dizileri-izle/page/",  "Netflix Dizileri"),
    )

    main_page = {
        # Ana sayfa her zaman ilk sırada (kök adres)
        "Ana Sayfa": f"{main_url}",
        "Son Bölümler": f"{main_url}/tum-bolumler/page/",
        "Yerli Diziler": f"{main_url}/yerli-dizi-izle/page/",
        "Yabancı Diziler": f"{main_url}/yabanci-dizi-izle/page/",
        "TV Programları": f"{main_url}/tv-programlari-izle/page/",
        "Netflix Dizileri": f"{main_url}/netflix-dizileri-izle/page/",
    }

    # ================================================================== #
    # Yardımcılar
    # ================================================================== #

    def generate_slug(self, title: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
        return slug or str(id(title))

    def _sayfa(self, sayfa: int = 1, url: str = "") -> str:
        """Kategori adresi + sayfa numarası (Kotlin: `${request.data}${page}/`)."""
        if not url or url.rstrip("/") == self.main_url.rstrip("/"):
            return f"{self.main_url}/"
        govde = re.sub(r"/\d+$", "", (url or "").rstrip("/"))
        return f"{govde}/{max(1, int(sayfa or 1))}/"

    @staticmethod
    def _meta_deger(secici: Selector, etiket: str) -> Optional[str]:
        """`span.dizimeta` etiketinin yanındaki değer (örn. 'Yapım Yılı :' -> '2026')."""
        for span in secici.css("span.dizimeta"):
            if span.re_first(etiket):
                kardeşler = span.xpath("following-sibling::text()").getall()
                deger = "".join(kardeşler).strip()
                if deger:
                    return deger
        return None

    # Bölüm -> dizi eşlemesi (aynı bölüm kartları ana sayfada tekrar tekrar görünür)
    _dizi_onbellek: Dict[str, str] = {}

    async def _dizi_url_bul(self, bolum_url: str) -> Optional[str]:
        """Bölüm adresinden dizi adresine.

        Slug'dan üretilen tahmin güvenilmez: `made-in-korea-2-sezon-2-bolum-izle`
        -> `made-in-korea-2-sezon-izle` üretiliyor ama gerçek adres
        `/diziler/made-in-korea-izle/`. Bu yüzden bölüm sayfasındaki
        `div#benzerli` bloğu okunur (Kotlin'ın yaptığı gibi).
        """
        if bolum_url in self._dizi_onbellek:
            return self._dizi_onbellek[bolum_url]

        try:
            istek = await self.httpx.get(bolum_url, headers=self.headers,
                                         follow_redirects=True, timeout=20.0)
            if istek.status_code != 200:
                return None
            secici = Selector(istek.text)
            adres = self.fix_url(secici.css("div#benzerli a::attr(href)").get() or "")
        except Exception:
            return None

        if adres:
            self._dizi_onbellek[bolum_url] = adres
        return adres or None

    @staticmethod
    def _bolum_url_mu(url: str) -> bool:
        """Bölüm adresi mi? `/{dizi}-N-bolum-izle/` veya `/{dizi}-N-sezon-M-bolum-izle/`"""
        return bool(re.search(r"-\d+-sezon-[\d-]+-bolum-izle/?$", url or "", re.IGNORECASE)) \
            or bool(re.search(r"-\d+-bolum-izle/?$", url or "", re.IGNORECASE))

    async def _dizi_adresine_coz(self, url: str) -> str:
        """Bölüm adresi verilmişse dizi adresine çevirir (Dizibox davranışı).

        NOT: `made-in-korea-2-sezon-izle` gibi `/diziler/` altında duran BÖLÜM
        slug'ları da oluşuyor. Bu yüzden `/diziler/` tek başına "dizi sayfası"
        sayılmaz; slug bölüm kalıbına uyuyorsa yine çözülür. Ayrıca dizi
        sayfasında sezon yoksa da çözüm denenir.
        """
        if not url:
            return url

        slug = url.rstrip("/").split("/")[-1]
        if self._bolum_url_mu(slug):
            cozulen = await self._dizi_url_bul(url)
            if cozulen:
                return cozulen

        # Slug dizi gibi görünüyor ama gerçek sayfa bölüm sayfasıysa (sezon yok)
        if "/diziler/" in url:
            try:
                istek = await self.httpx.get(url, headers=self.headers,
                                             follow_redirects=True, timeout=20.0)
                if istek.status_code == 200:
                    secici = Selector(istek.text)
                    if not secici.css("div.bolumust"):
                        cozulen = self.fix_url(
                            secici.css("div#benzerli a::attr(href)").get() or "")
                        if cozulen:
                            return cozulen
            except Exception:
                pass

        return url

    def _bolum_karti(self, kutu: Selector, category: str, dizi_url: str = "") -> Optional[MainPageResult]:
        """`div.episode-box` -> MainPageResult (Kotlin sonBolumler)

        `dizi_url` boşsa bölüm adresi kullanılır; doluysa kart diziye gider
        (böylece "Son Bölümler" listesinden doğrudan sezonlara ulaşılır).
        """
        ad = kutu.css("div.episode-name a")
        if not ad:
            return None

        bolum_url = self.fix_url(ad.css("::attr(href)").get() or "")
        if not bolum_url:
            return None

        ham_baslik = self.clean_title(ad.css("::text").get() or "")
        poster = kutu.css("a img::attr(data-src)").get() or kutu.css("a img::attr(src)").get()

        # "Halef 4.Sezon 3.Bölüm" -> sezon/bölüm numaraları
        sezon = bolum = None
        m_s = re.search(r"(\d+)\s*\.\s*Sezon", ham_baslik, re.IGNORECASE)
        m_b = re.search(r"(\d+)\s*\.\s*Bölüm", ham_baslik, re.IGNORECASE)
        if m_s:
            sezon = int(m_s.group(1))
        if m_b:
            bolum = int(m_b.group(1))

        dizi_adi = re.sub(r"\s*\d+\s*\.\s*Bölüm.*$", "", ham_baslik).strip()
        etiket = f"{dizi_adi} S{sezon:02d}E{bolum:02d}" if sezon and bolum else (dizi_adi or ham_baslik)

        return MainPageResult(
            category=category,
            title=etiket,
            url=dizi_url or bolum_url,
            episode_url=bolum_url,
            poster=self.fix_url(poster) if poster else None,
            release_date=(kutu.css("div.episode-date::text").get() or "").strip() or None,
            plugin=self.name,
            media_type="series",
            season=sezon,
            episode=bolum,
        )

    def _dizi_karti(self, kutu: Selector, category: str) -> Optional[MainPageResult]:
        """`div.single-item` -> MainPageResult (Kotlin diziler)"""
        baslik_el = kutu.css("div.categorytitle a")
        if not baslik_el:
            return None

        baslik = self.clean_title(baslik_el.css("::text").get() or "")
        href = self.fix_url(kutu.css("div.cat-img a::attr(href)").get() or "")
        if not baslik or not href:
            return None

        poster = kutu.css("div.cat-img img::attr(data-src)").get() or kutu.css("div.cat-img img::attr(src)").get()

        return MainPageResult(
            category=category,
            title=baslik,
            url=href,
            poster=self.fix_url(poster) if poster else None,
            plugin=self.name,
            media_type="series",
        )

    # ================================================================== #
    # Zorunlu metotlar
    # ================================================================== #

    async def get_main_page(self, page: int = 1, url: str = "", category: str = "") -> list[MainPageResult]:
        hedef = self._sayfa(page, url)
        istek = await self.httpx.get(hedef, headers=self.headers, follow_redirects=True, timeout=30.0)
        if istek.status_code != 200:
            return []

        secici = Selector(istek.text)

        # "Son Bölümler" ve ana sayfa bölüm kutuları kullanır
        if not url or "tum-bolumler" in url or url.rstrip("/") == self.main_url.rstrip("/"):
            kutular = secici.css("div.episode-box")
            bolumler = [k for k in (self._bolum_karti(k, category) for k in kutular) if k]
            # Kartlar dizi adresine yönlensin (Kotlin davranışı); slug'dan türetilir,
            # türetilemezse bölüm sayfasındaki `div#benzerli` bloğu okunur.
            dizi_adresleri = await asyncio.gather(*(
                self._dizi_url_bul(k.url) for k in bolumler
            ))
            for kart, dizi_url in zip(bolumler, dizi_adresleri):
                if dizi_url:
                    kart.url = dizi_url
            return bolumler

        kutular = secici.css("div.single-item")
        return [k for k in (self._dizi_karti(k, category) for k in kutular) if k]

    async def search(self, query: str) -> list[SearchResult]:
        # Site arama uçlarını (/?s=) 403 ile engelliyor; bu durumda
        # `?s=` yerine WordPress'in varsayılan arama yolunu deniyoruz.
        for arama_url in (f"{self.main_url}/?s={query}",
                          f"{self.main_url}/ara/?q={query}"):
            try:
                istek = await self.httpx.get(
                    url=arama_url,
                    headers={"Referer": f"{self.main_url}/"},
                    follow_redirects=True,
                    timeout=30.0,
                )
            except Exception as e:
                print(f"[!] {self.name} arama hatası ({arama_url}): {e}")
                continue

            if istek.status_code != 200:
                print(f"[!] {self.name}: arama HTTP {istek.status_code} ({arama_url})")
                continue

            secici = Selector(istek.text)
            kutular = secici.css("div.single-item")
            if not kutular:
                continue

            results = []
            for kutu in kutular:
                kart = self._dizi_karti(kutu, "")
                if not kart:
                    continue
                results.append(SearchResult(
                    title=kart.title,
                    url=kart.url,
                    poster=kart.poster,
                    media_type="series",
                    plugin=self.name,
                ))
            if results:
                return results

        print(f"[!] {self.name}: '{query}' için arama sonucu alınamadı (site 403 döndürüyor).")
        return []

    async def load_item(self, url: str) -> Optional[SeriesInfo]:
        return await self.load_series(url)

    async def load_series(self, url: str) -> Optional[SeriesInfo]:
        # Bölüm adresi geldiyse önce dizi adresine çevir (Dizibox davranışı):
        # "herhangi bir bölümden dizinin detay sayfası açılmalı".
        url = await self._dizi_adresine_coz(url)

        istek = await self.httpx.get(url, headers={"Referer": f"{self.main_url}/"},
                                    follow_redirects=True, timeout=30.0)
        if istek.status_code != 200:
            return None

        secici = Selector(istek.text)
        # Başlık iç içe etiketlerde olduğu için `::text` yerine normalize-space kullanıyoruz
        h1 = secici.css("div.title h1") or secici.css("h1")
        baslik = self.clean_title(h1[0].xpath("normalize-space(.)").get() if h1 else "")
        if not baslik:
            return None

        poster = secici.css("div.category_image img::attr(data-src)").get() \
            or secici.css("div.category_image img::attr(src)").get() or ""

        yil = self._meta_deger(secici, "Yapım Yılı")
        puan = self._meta_deger(secici, "IMDB")
        oyuncular_metin = self._meta_deger(secici, "Oyuncular") or ""
        oyuncular = [o.strip() for o in oyuncular_metin.split(",") if o.strip()]
        turler = [t.strip() for t in secici.css("div.genres a::text").getall() if t.strip()]
        ozet = self.clean_title(secici.css("div.category_desc::text").get() or "")

        # --- SEZON VE BÖLÜMLER ---
        seasons_dict: Dict[str, List[Episode]] = {}
        for kutu in secici.css("div.bolumust"):
            baslik_el = kutu.css("div.baslik::text").get()
            href = self.fix_url(kutu.css("a::attr(href)").get() or "")
            if not baslik_el or not href:
                continue

            ham = baslik_el.strip()
            m_s = re.search(r"(\d+)\s*\.\s*Sezon", ham, re.IGNORECASE)
            m_b = re.search(r"(\d+)\s*\.\s*Bölüm", ham, re.IGNORECASE)
            ep_s = int(m_s.group(1)) if m_s else 1
            ep_e = int(m_b.group(1)) if m_b else 1

            # Episode modeli "sezon/bölüm" içeren başlıkları boşaltıyor; sitedeki isimler de
            # "1.Sezon 1.Bölüm" biçiminde olduğu için bu durumda dizi adını kullanıyoruz
            ep_title = self.clean_title(re.sub(r"\s*izle$", "", ham, flags=re.IGNORECASE))
            if not ep_title or re.search(r"\d+\s*\.\s*Sezon|\d+\s*\.\s*Bölüm", ep_title, re.IGNORECASE):
                ep_title = baslik
            else:
                ep_title = re.sub(rf"^{re.escape(baslik)}\s*", "", ep_title).strip() or baslik

            episode_obj = Episode(
                season=ep_s,
                episode=ep_e,
                season_number=ep_s,
                episode_number=ep_e,
                title=ep_title,
                url=href,
            )
            seasons_dict.setdefault(str(ep_s), []).append(episode_obj)

        for liste in seasons_dict.values():
            liste.sort(key=lambda b: (b.episode or 0))

        return SeriesInfo(
            content_type="series",
            url=url,
            poster=self.fix_url(poster) if poster else None,
            title=baslik,
            description=ozet or None,
            tags=turler,
            rating=puan,
            year=yil,
            actors=oyuncular,
            plugin=self.name,
            seasons=seasons_dict if seasons_dict else None,
        )

    async def load_links(self, url: str) -> List[str]:
        """Bölüm sayfasındaki iframe adreslerini toplar (çözüm ExtractorManager'a bırakılır)."""
        if not url:
            return []

        # ── Oturum açma denemesi: KALDIRILDI (2026-10-02) ────────────────────
        #
        # Canlı doğrulama: bölüm sayfası HERKESE AÇIK. İframe adresi ham HTML'in
        # içinde geliyor; oturum açmadan da `div.video p iframe` bulundu ve
        # load_links doğru oynatıcı adresini döndürdü. Ayrıca bu POST'un yanıtı
        # hiçbir yerde kontrol edilmiyordu: try/except yalnızca ağ hatasını
        # yutuyor, başarı/başarısızlık sonucu hiçbir şeye etkilemiyordu.
        #
        # Yani bu blok her bölüm izlemede üçüncü taraf siteye boşuna bir giriş
        # POST'u gönderiyor, hiçbir işe yaramıyordu ve yalnızca IP rate-limit'e
        # takılma riski taşıyordu. Gerçek login bilgileri gerektiği için de
        # (log/pwd düz metin) kaynak kodunda tutulmamalı.
        #
        # Gerekirse geri almak için:
        # try:
        #     await self.httpx.post(
        #         url=f"{self.main_url}/wp-login.php",
        #         headers={**self.player_headers, "Referer": f"{self.main_url}/"},
        #         data={
        #             "log": "kullanici",
        #             "pwd": "parola",
        #             "rememberme": "forever",
        #             "redirect_to": self.main_url,
        #         },
        #         timeout=30.0,
        #     )
        # except Exception as e:
        #     print(f"[!] {self.name} oturum açma hatası: {e}")

        try:
            istek = await self.httpx.get(url, headers={**self.player_headers, "Referer": f"{self.main_url}/"},
                                        follow_redirects=True, timeout=30.0)
            secici = Selector(istek.text)
        except Exception as e:
            print(f"[!] {self.name} load_links hatası: {e}")
            return []

        embed_urls: List[str] = []

        # Lazy-load: site iframe'i `src="about:blank"` + `data-src=<gerçek>`
        # olarak gönderiyor. `.get()` ilk (yer tutucu) iframe'i seçtiği için
        # `div.video p iframe::attr(src)` "about:blank" döndürüyordu ve API
        # 200 ile {links: ["about:blank"]} veriyordu — hatasız, sessiz bozukluk.
        # self.gomulu_adresler() doğru sırayı (data-src -> src) uygular.
        if ana_iframe := self.gomulu_adres(secici, "div.video p iframe"):
            embed_urls.append(ana_iframe)

        # Alternatif kaynak sayfaları (her biri kendi iframe'ini içerir)
        for kaynak in secici.css("div.sources a::attr(href)").getall():
            if not kaynak:
                continue
            try:
                alt_istek = await self.httpx.get(self.fix_url(kaynak),
                                                  headers={**self.player_headers, "Referer": f"{self.main_url}/"},
                                                  follow_redirects=True, timeout=30.0)
                alt_secici = Selector(alt_istek.text)
                alt_iframe = self.gomulu_adres(alt_secici, "div.video p iframe")
                if alt_iframe and alt_iframe not in embed_urls:
                    embed_urls.append(alt_iframe)
            except Exception as e:
                print(f"[!] {self.name} alternatif kaynak hatası: {e}")

        return embed_urls


if __name__ == "__main__":
    import asyncio

    async def main():
        plugin = DiziMom()
        test = await plugin.get_main_page(1)
        print(test[0] if test else "Sonuç yok")
        # await plugin.search("halef")
        # print((await plugin.load_item("https://www.dizimom.wiki/diziler/vazgecilmez-izle/")).model_dump_json(indent=4))
        print(await plugin.load_links("https://www.dizimom.wiki/vazgecilmez-1-sezon-1-bolum-izle/"))
        await plugin.close()

    asyncio.run(main())