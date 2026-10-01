# Bu araç @keyiflerolsun tarafından | @KekikAkademi için yazılmıştır.

from Core import HTMLHelper
import asyncio
import time
import base64
import contextlib
import re
import sys
import urllib.parse
from pathlib import Path

import rich
from Kekik.Sifreleme import CryptoJS
from parsel import Selector

from Core.Extractor import ExtractResult
from Core.Helpers import konsol
from Core.Plugin.PluginBase import PluginBase
from Core.Plugin.PluginModels import Episode, MainPageResult, SearchResult, SeriesInfo

class DiziBox(PluginBase):
    name        = "DiziBox"
    language    = "tr"
    main_url    = "https://www.dizibox.live"
    favicon     = f"https://www.google.com/s2/favicons?domain={main_url}&sz=256"
    description = "Yabancı Dizi izle, Tüm yabancı dizilerin yeni ve eski sezonlarını full hd izleyebileceğiniz elit site."
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:101.0) Gecko/20100101 Firefox/101.0",
        "Referer": f"{main_url}/dizi-arsivi/",
    }
    cookies = {
        "LockUser"      : "true",
        "isTrustedUser" : "true",
        "dbxu"          : "1722403730363"
    }
    main_page = {
        "Ana Sayfa"            : main_url,
        "Son Bölümler"      : f"{main_url}/tum-bolumler/page/SAYFA/",
        "Popüler Diziler"   : f"{main_url}/tum-bolumler/page/SAYFA/?tip=populer",
        "Yeni Eklenenler"   : f"{main_url}/dizi-arsivi/page/SAYFA/",
        "Yerli"             : f"{main_url}/dizi-arsivi/page/SAYFA/?ulke[]=turkiye&yil=&imdb",
        # "Aile"              : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=aile&yil&imdb",
        "Aksiyon"           : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=aksiyon&yil&imdb",
        # "Animasyon"         : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=animasyon&yil&imdb",
        # "Belgesel"          : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=belgesel&yil&imdb",
        "Bilimkurgu"        : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=bilimkurgu&yil&imdb",
        # "Biyografi"         : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=biyografi&yil&imdb",
        "Dram"              : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=dram&yil&imdb",
        # "Drama"             : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=drama&yil&imdb",
        "Fantastik"         : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=fantastik&yil&imdb",
        "Gerilim"           : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=gerilim&yil&imdb",
        # "Gizem"             : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=gizem&yil&imdb",
        "Komedi"            : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=komedi&yil&imdb",
        # "Korku"             : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=korku&yil&imdb",
        # "Macera"            : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=macera&yil&imdb",
        # "Müzik"             : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=muzik&yil&imdb",
        # "Müzikal"           : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=muzikal&yil&imdb",
        # "Reality TV"        : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=reality-tv&yil&imdb",
        "Romantik"          : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=romantik&yil&imdb",
        # "Savaş"             : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=savas&yil&imdb",
        # "Spor"              : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=spor&yil&imdb",
        # "Suç"               : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=suc&yil&imdb",
        # "Tarih"             : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=tarih&yil&imdb",
        # "Western"           : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=western&yil&imdb",
        # "Yarışma"           : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=yarisma&yil&imdb",
}

    async def get_main_page(self, page: int = 1, url: str = "", category: str = "") -> list[MainPageResult] | dict[str, list[MainPageResult]]:
        clean_url = (url or "").strip()
        is_home_url = not clean_url or clean_url.rstrip("/") == self.main_url.rstrip("/")

        # Eğer belirli bir kategori veya ana sayfa harici bir URL verilmişse kategori sayfasına yönlendir
        if (clean_url and not is_home_url) or category:
            return await self.get_category_page(page=page, category=category, url=clean_url)

        # Varsayılan ana sayfa
        fetch_url = f"{self.main_url}/"
        istek = await self.client.get(
            url              = fetch_url,
            follow_redirects = True,
            timeout          = 30,
            headers          = self.headers,
            cookies          = self.cookies
        )
        if istek.status_code == 403:
            istek = await self.async_cf_get(fetch_url, headers=self.headers)
            secici = Selector(istek)
        else:
            secici = Selector(istek.text)
        
        container = secici.xpath(
            '//comment()[contains(.,"POPULAR SERIES")]/parent::*'
        )
        sections = container.xpath('./section') if container else []

        popular_series = []
        new_episodes = []

        if len(sections) > 0:
            for veri in sections[0].css("article.article-episode-card"):
                title = veri.css("img.afis::attr(alt)").get()
                link = veri.css("article.article-episode-card a.figure-link::attr(href)").get()
                poster = veri.css("img.afis::attr(data-src)").get() or veri.css("img.afis::attr(src)").get()
                pub_date = veri.css("div.publish-date::text").get()
                popular_series.append(
                    MainPageResult(
                        category="Popüler Diziler",
                        title=title.strip() if title else None,
                        url=self.fix_url(link),
                        poster=self.fix_url(poster),
                        release_date=pub_date.strip() if pub_date else None,
                        plugin=self.name,
                    )
                )

        if len(sections) > 1:
            for veri in sections[1].css("article.article-episode-card"):
                title = veri.css("img.afis::attr(alt)").get()
                link = veri.css("article.article-episode-card a.figure-link::attr(href)").get()
                poster = veri.css("img.afis::attr(data-src)").get() or veri.css("img.afis::attr(src)").get()
                pub_date = veri.css("div.publish-date::text").get()
                new_episodes.append(
                    MainPageResult(
                        category="Yeni Bölümler",
                        title=title.strip() if title else None,
                        url=self.fix_url(link),
                        poster=self.fix_url(poster),
                        release_date=pub_date.strip() if pub_date else None,
                        plugin=self.name,
                    )
                )

        return {"popular_series": popular_series, "new_episodes": new_episodes}

    async def get_category_page(self, page: int = 1, category: str = "", url: str = "") -> list[MainPageResult]:
        target_url = ""
        if url:
            target_url = url
        elif category:
            if category.startswith("http"):
                target_url = category
            else:
                target_url = self.main_page.get(category, "")

        if not target_url:
            return []

        if page == 1:
            if "/page/SAYFA/" in target_url:
                if "?" in target_url:
                    base = target_url.split("/page/SAYFA/")[0]
                    query_part = target_url.split("?", 1)[1]
                    fetch_url = f"{base}/?{query_part}"
                else:
                    base = target_url.split("/page/SAYFA/")[0]
                    fetch_url = f"{base}/"
            elif "SAYFA" in target_url:
                fetch_url = target_url.replace("SAYFA", "1")
            else:
                fetch_url = target_url
        else:
            if "SAYFA" in target_url:
                fetch_url = target_url.replace("SAYFA", str(page))
            elif "/page/" in target_url:
                fetch_url = re.sub(r"/page/\d+/", f"/page/{page}/", target_url)
            else:
                fetch_url = target_url

        try:
            istek = await self.httpx.get(
                url              = fetch_url,
                follow_redirects = True,
                timeout          = 30,
                headers          = self.headers,
                cookies          = self.cookies
            )
            if istek.status_code != 200:
                return []

            secici = Selector(istek.text)
            results = []
            for veri in secici.css("article.detailed-article, article.article-episode-card"):
                title_tag = veri.css("h3 a")
                if title_tag:
                    # 1. detailed-article formatı (/dizi-arsivi/ vb.)
                    title = title_tag.css("::text").get()
                    item_url = title_tag.css("::attr(href)").get()
                    desc = veri.css("div.post-summary::text").get()
                    description = desc.strip() if desc else None
                    cat_text = veri.css("span.custom-field::text").get()
                    cat = cat_text.strip().replace('\xa0', '').replace('|', '').strip() if cat_text else (category or None)
                    release_date = veri.css("span.custom-field").re_first(r"(\d{4})")
                    imdb = veri.css("span.label-imdb b::text").re_first(r"[\d.,]+")
                    langs = veri.css("span.custom-field").re(r"icon-globe.*?\d{4}\s*-\s*(.+?)\s*\|")
                    language = langs[0].strip() if langs else None
                else:
                    # 2. article-episode-card formatı (/tum-bolumler/ vb.)
                    title = (
                        veri.css("a.episode-card-title::attr(title)").get()
                        or veri.css("img.afis::attr(alt)").get()
                        or veri.css("a.episode-card-title::text").get()
                    )
                    item_url = veri.css("a.episode-card-title::attr(href)").get() or veri.css("a.figure-link::attr(href)").get()
                    description = None
                    cat = category or None
                    pub_date = veri.css("div.publish-date::text").get()
                    release_date = pub_date.strip() if pub_date else None
                    imdb = veri.css("span.label-imdb b::text").re_first(r"[\d.,]+")
                    lang_img = veri.css("div.language img::attr(alt)").get()
                    language = lang_img.strip() if lang_img else None

                if not title or not item_url:
                    continue

                img_tag = veri.css("img")
                poster = img_tag.css("::attr(data-src)").get() or img_tag.css("::attr(src)").get()

                results.append(
                    MainPageResult(
                        category=cat,
                        title=title.strip(),
                        url=self.fix_url(item_url),
                        poster=self.fix_url(poster),
                        description=description,
                        release_date=release_date,
                        rating=imdb,
                        language="ALTYAZI",#language,
                        plugin=self.name,
                    )
                )

            return results
        except Exception as e:
            print("Hata: ", e)
            return []

    async def get_random(self, count: int = 3) -> list[MainPageResult]:
        """
        DiziBox için rastgele DİZİ (bölüm değil, dizinin kendisi) seçer.
        Diziler '/dizi-arsivi/' altında yer alır.
        """
        import random

        # /dizi-arsivi/ içeren kategorileri filtrele (tüm türler ve yeni eklenenler)
        series_categories = [
            (cat, url) for cat, url in self.main_page.items()
            if "/dizi-arsivi/" in url
        ]

        if not series_categories:
            series_categories = [("Yeni Eklenenler", f"{self.main_url}/dizi-arsivi/page/SAYFA/")]

        random.shuffle(series_categories)
        items: list[MainPageResult] = []

        # Rastgele kategorilerden dizi çek
        for cat_name, cat_url in series_categories[:3]:
            random_page = random.randint(1, 3)
            try:
                page_items = await self.get_category_page(page=random_page, url=cat_url, category=cat_name)
                # Sadece gerçek dizi sayfalarını al (/diziler/ içerenler)
                series_items = [
                    it for it in page_items
                    if it.url and "/diziler/" in it.url
                ]
                items.extend(series_items)
                if len(items) >= count * 2:
                    break
            except Exception:
                continue

        # Yedek: Eğer yeterli sonuç gelmediyse 1. sayfadan garanti çek
        if len(items) < count:
            try:
                fallback_items = await self.get_category_page(
                    page=1,
                    url=f"{self.main_url}/dizi-arsivi/page/SAYFA/",
                    category="Yeni Eklenenler"
                )
                items.extend([it for it in fallback_items if it.url and "/diziler/" in it.url])
            except Exception:
                pass

        # Tekilleştir
        unique_items = list({it.url: it for it in items if it.url}.values())
        if not unique_items:
            return []

        if len(unique_items) <= count:
            return unique_items

        return random.sample(unique_items, count)
        
    async def search(self, query: str) -> list[SearchResult]:
        self.httpx.cookies.update(self.cookies)
        istek  = await self.httpx.get(f"{self.main_url}/?s={query}")
        secici = Selector(istek.text)

        

        return [
            SearchResult(
                title  = item.css("h3 a::text").get(),
                url    = self.fix_url(item.css("h3 a::attr(href)").get()),
                plugin = self.name,
                media_type= "Dizi",
                poster = self.fix_url(item.css("img::attr(src)").get()),
            )
                for item in secici.css("article.detailed-article")
        ]


    # İçerik detayları için bellek içi önbellek (URL -> (timestamp, SeriesInfo))
    _detail_cache: dict[str, tuple[float, SeriesInfo]] = {}

    async def load_item(self, url: str) -> SeriesInfo:
        now = time.time()
        # Eğer URL daha önce önbelleğe alınmışsa (15 dakika geçerli)
        if url in self._detail_cache:
            c_time, c_data = self._detail_cache[url]
            if now - c_time < 900:
                return c_data

        target_url = url
        # Eğer bir bölüm sayfası URL'si verilmişse direkt regex ile ana dizi sayfasına dönüştür (1 HTTP isteği tasarrufu)
        m = re.search(r"/([a-z0-9-]+?)-\d+-sezon-\d+-bolum", url)
        if m:
            potential_series_url = f"{self.main_url}/diziler/{m.group(1)}/"
            if potential_series_url in self._detail_cache:
                c_time, c_data = self._detail_cache[potential_series_url]
                if now - c_time < 900:
                    return c_data
            target_url = potential_series_url

        try:
            istek = await self.httpx.get(target_url)
            if istek.status_code == 200:
                secici = Selector(istek.text)
                url = target_url
            else:
                raise ValueError("Ana dizi URL doğrudan açılamadı")
        except Exception:
            istek = await self.httpx.get(url)
            secici = Selector(istek.text)

            # Eğer bir bölüm sayfası açılmışsa ve archive_link varsa
            archive_link = secici.css("div#archive-box a.archive-title::attr(href)").get()
            if archive_link:
                url = self.fix_url(archive_link)
                istek = await self.httpx.get(url)
                secici = Selector(istek.text)
        time.sleep(0.1)
        title       = secici.css("div.tv-overview h1 a::text").get()
        poster      = self.fix_url(secici.css("div.tv-overview figure img::attr(src)").get())
        description = secici.css("div.tv-story p::text").get()
        year        = secici.css("a[href*='/yil/']::text").re_first(r"(\d{4})")
        tags        = secici.css("a[href*='/tur/']::text").getall()
        rating      = secici.css("span.label-imdb b::text").re_first(r"[\d.,]+")
        actors      = [actor.css("::text").get() for actor in secici.css("a[href*='/oyuncu/']")]
        fragman     = secici.css(".embed-responsive-item > iframe::attr(src)").get()

        sezon_links = secici.css("div#seasons-list a::attr(href)").getall()

        # Tüm sezonları paralel (asyncio.gather) olarak hızlıca çek
        async def fetch_single_season(sezon_link):
            sezon_url = self.fix_url(sezon_link)
            if not sezon_url or not sezon_url.startswith("http"):
                return []
            try:
                sezon_istek = await self.httpx.get(sezon_url)
                if sezon_istek.status_code != 200:
                    return []
                sezon_secici = Selector(sezon_istek.text)
                ep_list = []
                for bolum in sezon_secici.css("article.grid-box"):
                    ep_secici  = bolum.css("div.post-title a::text")
                    ep_title   = ep_secici.get()
                    ep_href    = self.fix_url(bolum.css("div.post-title a::attr(href)").get())
                    ep_season  = ep_secici.re_first(r"(\d+)\. ?Sezon")
                    ep_episode = ep_secici.re_first(r"(\d+)\. ?Bölüm")

                    if ep_title and ep_href:
                        ep_list.append(Episode(
                            season  = ep_season,
                            episode = ep_episode,
                            title   = ep_title,
                            url     = ep_href,
                        ))
                return ep_list
            except Exception:
                return []

        if sezon_links:
            results = await asyncio.gather(*(fetch_single_season(link) for link in sezon_links))
            episodes = [ep for sublist in results for ep in sublist]
        else:
            episodes = []

        seasons_dict: dict[int, list[Episode]] = {}
        for ep in episodes:
            try:
                s_num = int(ep.season) if ep.season is not None else 1
            except (ValueError, TypeError):
                s_num = 1
            if s_num not in seasons_dict:
                seasons_dict[s_num] = []
            seasons_dict[s_num].append(ep)

        result_info = SeriesInfo(
            plugin      = self.name,
            url         = url,
            poster      = poster,
            title       = title,
            description = description,
            tags        = tags,
            rating      = rating,
            year        = year,
            actors      = actors,
            fragman_url     = fragman,
            seasons     = seasons_dict if seasons_dict else len(sezon_links),

        )

        # Sonuçları hem orijinal URL hem de dizi URL'si ile önbelleğe al
        self._detail_cache[url] = (now, result_info)
        if target_url != url:
            self._detail_cache[target_url] = (now, result_info)

        return result_info

    async def _iframe_decode(self, name: str, iframe_link: str, referer: str) -> list[dict]:
        results = []
        if not iframe_link or not isinstance(iframe_link, str):
            return results

        try:
            if "/player/king/king.php" in iframe_link:
                iframe_link = iframe_link.replace("king.php?v=", "king.php?wmode=opaque&v=")
                self.httpx.headers.update({"Referer": referer})

                istek  = await self.httpx.get(iframe_link)
                secici = Selector(istek.text)
                iframe = secici.css("div#Player iframe::attr(src)").get() or secici.css("iframe::attr(src)").get()

                if iframe:
                    iframe = self.fix_url(iframe)
                    self.httpx.headers.update({"Referer": self.main_url})
                    istek = await self.httpx.get(iframe)

                    crypt_match = re.search(r"CryptoJS\.AES\.decrypt\(\"(.*)\",\"", istek.text)
                    pass_match = re.search(r"\",\"(.*)\"\);", istek.text)

                    if crypt_match and pass_match:
                        try:
                            crypt_data = crypt_match[1]
                            crypt_pass = pass_match[1]
                            decode = CryptoJS.decrypt(crypt_pass, crypt_data)

                            if video_match := re.search(r"file: '(.*)',", decode):
                                results.append({
                                    "name": "King",
                                    "url": video_match[1],
                                    "headers": {
                                        "User-Agent": self.headers["User-Agent"],
                                        "Cookie": self.cookies,
                                    },
                                    "referer": video_match[1]
                                })
                            else:
                                results.append({
                                    "name": "King",
                                    "url": iframe,
                                    "headers": {
                                        "User-Agent": self.headers["User-Agent"],
                                        "Cookie": self.cookies,
                                    },
                                    "referer": iframe
                                })
                        except Exception as e:
                            konsol.log(f"CryptoJS decrypt error: {e}")
                            results.append({
                                "name": "King",
                                "url": iframe,
                                "headers": {
                                    "User-Agent": self.headers["User-Agent"],
                                    "Cookie": self.cookies,
                                },
                                "referer": iframe
                            })
                    else:
                        results.append({
                            "name": "King",
                            "url": iframe,
                            "headers": {
                                "User-Agent": self.headers["User-Agent"],
                                "Cookie": self.cookies,
                            },
                            "referer": iframe
                        })

            elif "/player/moly/moly.php" in iframe_link:
                iframe_link = iframe_link.replace("moly.php?h=", "moly.php?wmode=opaque&h=")
                self.httpx.headers.update({"Referer": referer})
                for _ in range(5):
                    await asyncio.sleep(0.3)
                    try:
                        istek = await self.httpx.get(iframe_link)
                        atob_match = re.search(r"unescape\(\"(.*)\"\)", istek.text)
                        if atob_match:
                            decoded_atob = urllib.parse.unquote(atob_match[1])
                            str_atob = base64.b64decode(decoded_atob).decode("utf-8")
                            if iframe := Selector(str_atob).css("div#Player iframe::attr(src)").get():
                                fixed_iframe = self.fix_url(iframe)
                                if fixed_iframe and fixed_iframe.startswith("http"):
                                    results.append({
                                        "name": "Moly",
                                        "url": fixed_iframe,
                                        "headers": {
                                            "User-Agent": self.headers["User-Agent"]
                                        },
                                        "referer": ""
                                    })
                                    break
                    except Exception:
                        continue

            elif "/player/haydi.php" in iframe_link:
                try:
                    parts = iframe_link.split("?v=")
                    if len(parts) > 1:
                        okru_url = base64.b64decode(parts[-1]).decode("utf-8")
                        if okru_url and okru_url.startswith("http"):
                            results.append({
                                "name": "Okru",
                                "url": okru_url,
                                "headers": {
                                    "User-Agent": self.headers["User-Agent"],
                                },
                                "referer": ""
                            })
                except Exception as e:
                    konsol.log(f"Haydi decode error: {e}")

            else:
                # Standalone/direct embed player
                if iframe_link.startswith("http"):
                    results.append({
                        "name": name or "Dizibox",
                        "url": iframe_link,
                        "headers": {
                            "User-Agent": self.headers["User-Agent"],
                        },
                        "referer": referer
                    })
        except Exception as e:
            konsol.log(f"_iframe_decode exception ({iframe_link}): {e}")

        return results


    async def load_links(self, url: str) -> list[ExtractResult]:
        if not url:
            return []

        # Eğer dizi ana sayfası verilmişse (/diziler/...) ilk bölümün linklerini getir
        if "/diziler/" in url:
            try:
                item = await self.load_item(url)
                if item and item.episodes:
                    return await self.load_links(item.episodes[0].url)
            except Exception as e:
                konsol.log(f"Dizi ana sayfası bölümleri yüklenirken hata: {e}")
        # httpx yerine Cloudflare bypass metodunu kullanıyoruz
        try:
            html_text = await self.async_cf_get(url, headers=self.headers)
        except Exception:
            istek = await self.client.get(url, headers=self.headers, cookies=self.cookies)
            html_text = istek.text
        secici = Selector(html_text)

        # Eğer video alanı yoksa ama dizi detay sayfasıysa ilk bölümü çekmeyi dene
        if not secici.css("div#video-area") and secici.css("div#seasons-list"):
            try:
                item = await self.load_item(url)
                if item and item.episodes:
                    return await self.load_links(item.episodes[0].url)
            except Exception:
                pass

        iframes = []
        if main_iframe := secici.css("div#video-area iframe::attr(src)").get():
            try:
                if decoded := await self._iframe_decode(self.name, self.fix_url(main_iframe), url):
                    iframes.extend(decoded)
            except Exception as e:
                konsol.log(f"Ana iframe çözülürken hata: {e}")

        for alternatif in secici.css("div.video-toolbar option[value]"):
            alt_name = alternatif.css("::text").get()
            alt_link = alternatif.css("::attr(value)").get()

            if not alt_link or alt_link.strip() in ("", "#") or alt_link.startswith("javascript"):
                continue

            alt_link = self.fix_url(alt_link)
            if not alt_link.startswith("http"):
                continue

            try:
                self.httpx.headers.update({"Referer": url})
                alt_istek = await self.httpx.get(alt_link)
                if alt_istek.status_code == 200:
                    alt_secici = Selector(alt_istek.text)
                    if alt_iframe := (alt_secici.css("div#video-area iframe::attr(src)").get() or alt_secici.css("iframe::attr(src)").get()):
                        if decoded := await self._iframe_decode(alt_name or "Alternatif", self.fix_url(alt_iframe), url):
                            iframes.extend(decoded)
            except Exception as e:
                konsol.log(f"Alternatif link çözülürken hata ({alt_name}): {e}")

        valid_results = []
        for iframe in iframes:
            i_url = iframe.get("url")
            if i_url and isinstance(i_url, str) and i_url.startswith("http"):
                valid_results.append(ExtractResult(
                    name    = iframe.get("name", "Dizibox"),
                    url     = i_url,
                    referer = iframe.get("referer", url),
                    headers = iframe.get("headers", {})
                ))

        return valid_results



if __name__ == "__main__":
    import asyncio

    async def main():
        plugin = DiziBox()
        # test = await plugin.get_main_page(1,url="https://www.dizibox.live/")
        # rich.print(test)
        # search = await plugin.search("spider-Noir")
        # rich.print(search)
        # category_test = await plugin.get_category_page(1,category="Aksiyon")
        # rich.print(category_test)
        # load_item = await plugin.load_item("https://www.dizibox.live/diziler/dutton-ranch/")
        # rich.print(load_item)
        load_links = await plugin.load_links("https://www.dizibox.live/silo-1-sezon-1-bolum-izle/")
        # load_links = await plugin.load_links("https://www.dizibox.live/dutton-ranch-1-sezon-5-bolum-izle/")
        konsol.print(load_links)
        await plugin.close()

    asyncio.run(main())