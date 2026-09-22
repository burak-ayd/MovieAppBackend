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
        "Yerli"         : f"{main_url}/dizi-arsivi/page/SAYFA/?ulke[]=turkiye&yil=&imdb",
        "Aile"          : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=aile&yil&imdb",
        "Aksiyon"       : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=aksiyon&yil&imdb",
        "Animasyon"     : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=animasyon&yil&imdb",
        "Belgesel"      : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=belgesel&yil&imdb",
        "Bilimkurgu"    : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=bilimkurgu&yil&imdb",
        "Biyografi"     : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=biyografi&yil&imdb",
        "Dram"          : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=dram&yil&imdb",
        "Drama"         : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=drama&yil&imdb",
        "Fantastik"     : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=fantastik&yil&imdb",
        "Gerilim"       : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=gerilim&yil&imdb",
        "Gizem"         : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=gizem&yil&imdb",
        "Komedi"        : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=komedi&yil&imdb",
        "Korku"         : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=korku&yil&imdb",
        "Macera"        : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=macera&yil&imdb",
        "Müzik"         : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=muzik&yil&imdb",
        "Müzikal"       : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=muzikal&yil&imdb",
        "Reality TV"    : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=reality-tv&yil&imdb",
        "Romantik"      : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=romantik&yil&imdb",
        "Savaş"         : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=savas&yil&imdb",
        "Spor"          : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=spor&yil&imdb",
        "Suç"           : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=suc&yil&imdb",
        "Tarih"         : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=tarih&yil&imdb",
        "Western"       : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=western&yil&imdb",
        "Yarışma"       : f"{main_url}/dizi-arsivi/page/SAYFA/?tur[0]=yarisma&yil&imdb",
}

    async def get_main_page(self, page: int=1, url: str="", category: str="") -> list[MainPageResult]:

        if not url == self.main_url:
            return self.get_category_page(page, category)

        if not url:
            url = f"{self.main_url}/"
        istek = await self.httpx.get(
            url              = f"{url}",
            follow_redirects = True,
            timeout=30,
            headers=self.headers,
            cookies=self.cookies
        )
        secici = Selector(istek.text)
        
        container = secici.xpath(
            '//comment()[contains(.,"POPULAR SERIES")]/parent::*'
        )

        sections = container.xpath('./section')

        popular_series_section = sections[0]
        new_episodes_section = sections[1]
        
        popular_series = [
            MainPageResult(
                category = category,
                title    = veri.css("img.afis::attr(alt)").get(),
                url      = self.fix_url(veri.css("article.article-episode-card a.figure-link::attr(href)").get()),
                poster   = self.fix_url(veri.css("img.afis::attr(data-src)").get()),
                release_date 	 = veri.css("div.publish-date::text").get(),
            )
                for veri in popular_series_section.css("article.article-episode-card")
        ]

        new_episodes = [
            MainPageResult(
                category = category,
                title    = veri.css("img.afis::attr(alt)").get(),
                url      = self.fix_url(veri.css("article.article-episode-card a.figure-link::attr(href)").get()),
                poster   = self.fix_url(veri.css("img.afis::attr(data-src)").get()),
                release_date 	 = veri.css("div.publish-date::text").get(),
            )
                for veri in new_episodes_section.css("article.article-episode-card")
        ]
        
        return {"popular_series": popular_series, "new_episodes": new_episodes}

    async def get_category_page(self, page: int=1, category: str="") -> list[MainPageResult]:
        if not category.startswith("http"):
            get_category_url = self.main_page.get(category)
        else:
            get_category_url = category
        
        url = get_category_url.replace("SAYFA", str(page))

        istek = await self.httpx.get(
            url              = f"{url}",
            follow_redirects = True,
            timeout=30,
            headers=self.headers,
            cookies=self.cookies
        )
        secici = Selector(istek.text)
        return [
            MainPageResult(
                category = veri.css("span.custom-field::text").get().strip().replace('\xa0', '').replace('|', '').replace(' ', ''),
                title    = veri.css("h3 a::text").get().strip(),
                url      = self.fix_url(veri.css("h3 a::attr(href)").get()),
                poster   = self.fix_url(veri.css("img::attr(src)").get()),
                description = veri.css("div.post-summary::text").get().strip(),
                release_date = veri.css("span.custom-field::text").re_first(r"(\d{4})"),
                imdb = veri.css("span.label-imdb b::text").re_first(r"[\d.,]+"),
                language = veri.css("span.custom-field").re(r"icon-globe.*?\d{4}\s*-\s*(.+?)\s*\|")[0]
            )
                for veri in secici.css("article.detailed-article")
        ]
        
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