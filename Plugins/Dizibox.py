# Bu araç @keyiflerolsun tarafından | @KekikAkademi için yazılmıştır.

import asyncio
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
    favicon     = f"https://www.google.com/s2/favicons?domain={main_url}&sz=64"
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
        "Son Bölümler"      : f"{main_url}/tum-bolumler/page/SAYFA/",
        "Popüler Diziler"   : f"{main_url}/tum-bolumler/page/SAYFA/?tip=populer",
        "Yeni Eklenenler"   : f"{main_url}/dizi-arsivi/page/SAYFA/",
        "Yerli"             : f"{main_url}/dizi-arsivi/page/SAYFA/?ulke[]=turkiye&yil=&imdb",
        "Aile"              : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=aile&yil&imdb",
        "Aksiyon"           : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=aksiyon&yil&imdb",
        "Animasyon"         : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=animasyon&yil&imdb",
        "Belgesel"          : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=belgesel&yil&imdb",
        "Bilimkurgu"        : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=bilimkurgu&yil&imdb",
        "Biyografi"         : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=biyografi&yil&imdb",
        "Dram"              : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=dram&yil&imdb",
        "Drama"             : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=drama&yil&imdb",
        "Fantastik"         : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=fantastik&yil&imdb",
        "Gerilim"           : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=gerilim&yil&imdb",
        "Gizem"             : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=gizem&yil&imdb",
        "Komedi"            : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=komedi&yil&imdb",
        "Korku"             : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=korku&yil&imdb",
        "Macera"            : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=macera&yil&imdb",
        "Müzik"             : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=muzik&yil&imdb",
        "Müzikal"           : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=muzikal&yil&imdb",
        "Reality TV"        : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=reality-tv&yil&imdb",
        "Romantik"          : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=romantik&yil&imdb",
        "Savaş"             : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=savas&yil&imdb",
        "Spor"              : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=spor&yil&imdb",
        "Suç"               : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=suc&yil&imdb",
        "Tarih"             : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=tarih&yil&imdb",
        "Western"           : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=western&yil&imdb",
        "Yarışma"           : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=yarisma&yil&imdb",
}

    async def get_main_page(self, page: int = 1, url: str = "", category: str = "") -> list[MainPageResult] | dict[str, list[MainPageResult]]:
        clean_url = (url or "").strip()
        is_home_url = not clean_url or clean_url.rstrip("/") == self.main_url.rstrip("/")

        # Eğer belirli bir kategori veya ana sayfa harici bir URL verilmişse kategori sayfasına yönlendir
        if (clean_url and not is_home_url) or category:
            return await self.get_category_page(page=page, category=category, url=clean_url)

        # Varsayılan ana sayfa
        fetch_url = f"{self.main_url}/"
        istek = await self.httpx.get(
            url              = fetch_url,
            follow_redirects = True,
            timeout          = 30,
            headers          = self.headers,
            cookies          = self.cookies
        )
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
                        language=language,
                        plugin=self.name,
                    )
                )

            return results
        except Exception as e:
            print("Hata: ", e)
            return []
        
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


    async def load_item(self, url: str) -> SeriesInfo:
        istek  = await self.httpx.get(url)
        secici = Selector(istek.text)

        # Eğer bir bölüm sayfası URL'si verilmişse ana dizi sayfasına yönlendir
        archive_link = secici.css("div#archive-box a.archive-title::attr(href)").get()
        if archive_link:
            url = self.fix_url(archive_link)
            istek = await self.httpx.get(url)
            secici = Selector(istek.text)

        title       = secici.css("div.tv-overview h1 a::text").get()
        poster      = self.fix_url(secici.css("div.tv-overview figure img::attr(src)").get())
        description = secici.css("div.tv-story p::text").get()
        year        = secici.css("a[href*='/yil/']::text").re_first(r"(\d{4})")
        tags        = secici.css("a[href*='/tur/']::text").getall()
        rating      = secici.css("span.label-imdb b::text").re_first(r"[\d.,]+")
        actors      = [actor.css("::text").get() for actor in secici.css("a[href*='/oyuncu/']")]

        episodes = []
        for sezon_link in secici.css("div#seasons-list a::attr(href)").getall():
            sezon_url    = self.fix_url(sezon_link)
            sezon_istek  = await self.httpx.get(sezon_url)
            sezon_secici = Selector(sezon_istek.text)

            for bolum in sezon_secici.css("article.grid-box"):
                ep_secici  = bolum.css("div.post-title a::text")

                ep_title   = ep_secici.get()
                ep_href    = self.fix_url(bolum.css("div.post-title a::attr(href)").get())
                ep_season  = ep_secici.re_first(r"(\d+)\. ?Sezon")
                ep_episode = ep_secici.re_first(r"(\d+)\. ?Bölüm")

                if ep_title and ep_href:
                    episodes.append(Episode(
                        season  = ep_season,
                        episode = ep_episode,
                        title   = ep_title,
                        url     = ep_href,
                    ))

        return SeriesInfo(
            url         = url,
            poster      = poster,
            title       = title,
            description = description,
            tags        = tags,
            rating      = rating,
            year        = year,
            episodes    = episodes,
            actors      = actors,
        )


    async def _iframe_decode(self, name:str, iframe_link:str, referer:str) -> list[str]:
        results = []

        if "/player/king/king.php" in iframe_link:
            iframe_link = iframe_link.replace("king.php?v=", "king.php?wmode=opaque&v=")
            self.httpx.headers.update({"Referer": referer})

            istek  = await self.httpx.get(iframe_link)
            secici = Selector(istek.text)
            iframe = secici.css("div#Player iframe::attr(src)").get()

            self.httpx.headers.update({"Referer": self.main_url})
            
            istek = await self.httpx.get(iframe)

            crypt_data = re.search(r"CryptoJS\.AES\.decrypt\(\"(.*)\",\"", istek.text)[1]
            crypt_pass = re.search(r"\",\"(.*)\"\);", istek.text)[1]
            decode     = CryptoJS.decrypt(crypt_pass, crypt_data)

            if video_match := re.search(r"file: '(.*)',", decode):
                results.append({
                    "name": "King",
                    "url": video_match[1],  
                    "headers": {
                        "User-Agent": self.headers["User-Agent"],
                        "Cookie": self.cookies,
                        },"referer": video_match[1]
                })
            else:
                # return iframe, user-agents and referer might be needed for some links
                konsol.log(f"Çözümleme başarısız, iframe: {iframe}, referer: {referer}")
                results.append({
                    "name": "king2",
                    "url": iframe,
                    "headers": {
                        "User-Agent": self.headers["User-Agent"],
                        "Cookie": self.cookies,
                    },"referer": iframe
                })

        elif "/player/moly/moly.php" in iframe_link:
            iframe_link = iframe_link.replace("moly.php?h=", "moly.php?wmode=opaque&h=")
            self.httpx.headers.update({"Referer": referer})
            while True:
                await asyncio.sleep(.3)
                with contextlib.suppress(Exception):
                    istek  = await self.httpx.get(iframe_link)

                    if atob_data := re.search(r"unescape\(\"(.*)\"\)", istek.text):
                        decoded_atob = urllib.parse.unquote(atob_data[1])
                        str_atob     = base64.b64decode(decoded_atob).decode("utf-8")

                    if iframe := Selector(str_atob).css("div#Player iframe::attr(src)").get():
                        results.append({
                            "name" : "Moly",
                            "url": iframe,
                            "headers": {
                                "User-Agent": self.headers["User-Agent"]
                            },"referer": ""
                        })

                    break

        elif "/player/haydi.php" in iframe_link:
            okru_url = base64.b64decode(iframe_link.split("?v=")[-1]).decode("utf-8")
            results.append({
                "name": "Okru",
                "url": okru_url,
                "headers": {
                    "User-Agent": self.headers["User-Agent"],
                     
                },"referer": ""
            })

        return results


    async def load_links(self, url: str) -> list[ExtractResult]:
        
        istek  = await self.httpx.get(url)
        secici = Selector(istek.text)
        # konsol.log(url)
        iframes = []
        if main_iframe := secici.css("div#video-area iframe::attr(src)").get():
            if decoded := await self._iframe_decode(self.name, main_iframe, url):
                iframes.extend(decoded)
        # konsol.log(iframes)
        for alternatif in secici.css("div.video-toolbar option[value]"):
            alt_name = alternatif.css("::text").get()
            alt_link = alternatif.css("::attr(value)").get()

            if not alt_link:
                continue

            self.httpx.headers.update({"Referer": url})
            alt_istek = await self.httpx.get(alt_link)
            alt_istek.raise_for_status()

            alt_secici = Selector(alt_istek.text)
            if alt_iframe := alt_secici.css("div#video-area iframe::attr(src)").get():
                if decoded := await self._iframe_decode(alt_name, alt_iframe, url):
                    iframes.extend(decoded)

        return [ExtractResult(
            name    = iframe.get("name", "Dizibox"),
            url     = iframe["url"],    
            referer = iframe["referer"],
            headers = iframe.get("headers", {})
        ) for iframe in iframes]



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