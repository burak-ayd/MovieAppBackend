from typing import List, Union
from bs4 import BeautifulSoup
from parsel import Selector
import base64, json
import random
import re
import string
import time
import uuid
from Core.Plugin.PluginBase import PluginBase
from Core.Plugin.PluginModels import SearchResult, MainPageResult, MovieInfo, SeriesInfo
from Core.Helpers.TitleHelper import TitleHelper
from Core.Helpers import konsol

class HDFilmCehennemi(PluginBase):
    """HDFilmCehennemi kaynak site kazıyıcısı."""

    name = "HDFilmCehennemi"
    language = "tr"
    main_url = "https://www.hdfilmcehennemi.nl"
    favicon = f"https://www.google.com/s2/favicons?domain={main_url}&sz=64"
    description = "Türkiye'nin en hızlı hd film izleme sitesi"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "X-Requested-With": "fetch",
        "Accept": "*/*",
        "Referer": f"{main_url}/category/film-izle-2/",
    }

    main_page = {
        "Yeni Eklenen Filmler"  : f"{main_url}",
        "Yeni Eklenen Diziler"  : f"{main_url}/yabancidiziizle-2",
        "Tavsiye Filmler"       : f"{main_url}/category/tavsiye-filmler-izle2",
        "IMDB 7+ Filmler"       : f"{main_url}/imdb-7-puan-uzeri-filmler",
        "En Çok Yorumlananlar"  : f"{main_url}/en-cok-yorumlananlar-1",
        "En Çok Beğenilenler"   : f"{main_url}/en-cok-begenilen-filmleri-izle",
        "Aile Filmleri"         : f"{main_url}/tur/aile-filmleri-izleyin-6",
        "Aksiyon Filmleri"      : f"{main_url}/tur/aksiyon-filmleri-izleyin-3",
        "Animasyon Filmleri"    : f"{main_url}/tur/animasyon-filmlerini-izleyin-4",
        "Belgesel Filmleri"     : f"{main_url}/tur/belgesel-filmlerini-izle-1",
        "Bilim Kurgu Filmleri"  : f"{main_url}/tur/bilim-kurgu-filmlerini-izleyin-2",
        "Komedi Filmleri"       : f"{main_url}/tur/komedi-filmlerini-izleyin-1",
        "Korku Filmleri"        : f"{main_url}/tur/korku-filmlerini-izle-2/",
        "Romantik Filmleri"     : f"{main_url}/tur/romantik-filmleri-izle-1",
    }

    async def get_main_page(self, page: int = 1, url: str = "", category: str = "") -> list[MainPageResult]:

        url = f"{self.main_url}/load/page/{page}/home"

        request = await self.httpx.get(url, follow_redirects=True, headers=self.headers)
        if request.status_code != 200:
            print("HTTP FAIL:", request.status_code)
            # break

        try:
            data = request.json()
        except:
            print("INVALID JSON")
            # break

        html = data.get("html")

        if not html or len(html) < 200:
            print("EMPTY/BROKEN PAGE -> STOP")
            # break
        selector = Selector(text=html)

        # title = selector.css("a::attr(title)").get()
        # url = selector.css("a::attr(href)").get()
        # poster = selector.css("div.poster-wrapper > img::attr(data-src)").get()
        # language = selector.css("div.poster-info > span.poster-lang > span::text").get()
        # year = selector.css("div.poster-meta > span::text").get()
        # imdb = selector.css("div.poster-meta > span.imdb::text").get()

        data = [
            MainPageResult(
                category=category,
                title=veri.css("strong.poster-title::text").get(),
                url=self.fix_url(veri.css("::attr(href)").get()),
                poster=self.fix_url(veri.css("img::attr(data-src)").get()),
                language=veri.css("div.poster-info > span.poster-lang > span::text").get().strip(),
                release_date=veri.css("div.poster-meta > span::text").get().strip(),
                imdb=veri.css("div.poster-meta > span.imdb::text").get().strip(),
                plugin=self.name,
            )
            for veri in selector.css("a.poster")
        ]
        return data

    async def search(self, query: str) -> list[SearchResult]:
        request = await self.httpx.get(
            url=f"{self.main_url}/search/?q={query}",
            headers={"Referer": f"{self.main_url}/", "X-Requested-With": "fetch", "authority": f"{self.main_url}"},
        )
        results = []
        for veri in request.json().get("results"):
            secici = Selector(veri)
            title = secici.css("h4.title::text").get()
            href = secici.css("a::attr(href)").get()
            poster = secici.css("img::attr(data-src)").get() or secici.css("img::attr(src)").get()
            year = secici.css("span.year::text").get().strip()
            rating = secici.css("div.meta span.imdb::text").re_first(r"(\d+(?:\.\d+)?)")
            media_type = secici.css("div.meta span.type::text").get().strip()
            if title and href:
                results.append(
                    SearchResult(
                        title=title.strip(),
                        url=self.fix_url(href.strip()),
                        poster=self.fix_url(poster.strip()) if poster else None,
                        year=year,
                        rating=rating,
                        plugin=self.name,
                        media_type= media_type
                        
                    )
                )
        return results

    def generate_slug(self, title: str) -> str:
        slug = title.lower()
        slug = re.sub(r"[^a-z0-9]+", "-", slug)
        slug = slug.strip("-")
        return slug or str(uuid.uuid4())

    async def load_item(self, url: str) -> MovieInfo:
        istek = await self.httpx.get(url, headers={"Referer": f"{self.main_url}/"})
        secici = Selector(istek.text)
        if "404 Hata - Sayfa Bulunamadı" in str(secici):
            return None

        try:
            title = secici.css("h1.section-title::text").get().strip()
            original_title = secici.css("h1.section-title small::text").get()

            if original_title.split("(")[0].strip() != " ":
                original_title = original_title.split("(")[0].strip()
            if original_title == "" and "-" in title:
                original_title = title.split("-")[-1].strip()
            if original_title == "":
                original_title = title
            poster = secici.css("aside.post-info-poster img.lazyload::attr(data-src)").get().strip()
            description = secici.css("article.post-info-content > p::text").get().strip()
            genre = secici.css("div.post-info-genres a::text").getall()
            rating = secici.css("div.post-info-imdb-rating span::text").get().strip()
            vote_count = (
                secici.css("div.post-info-imdb-rating small::text")
                .get()
                .replace("(", "")
                .replace(")", "")
                .replace("oy", "")
                .strip()
            )
            year = secici.css("div.post-info-year-country a::text").getall()[0].strip()
            country = secici.css("div.post-info-year-country a::text").getall()[1].strip()
            actors = secici.css("div.post-info-cast a > strong::text").getall()
            duration = secici.css("div.post-info-duration::text").get().replace("dakika", "").strip()
            imdb = secici.css("div.post-info-imdb a::attr(data-id)").get().strip()
            fragman = secici.css("div.post-info-trailer button::attr(data-modal)").get().strip()
        except Exception as e:
            print(f"Link: {url} - Hata: {e}")
            return None

        data = MovieInfo(
            url=url,
            poster_url=self.fix_url(poster),
            title=self.clean_title(title),
            original_title=self.clean_title(original_title),
            description=description,
            slug=self.generate_slug(self.clean_title(title)),
            genre=genre,
            rating=rating,
            release_date=year,
            country=country,
            vote_count=vote_count,
            cast_members=actors,
            runtime_minutes=int(duration),
            imdb_id=imdb,
            fragman_url=fragman,
        )

        # IMDb'den eksik alanları doldur (director, creator, country, language,
        # vote_count, age_rating, production_co, original_title, tagline, status …)
        # print(data.model_dump_json(indent=4, ensure_ascii=False))
        # exit()

        return data

    async def load_links(self, url: str) -> List[str]:
        embed_urls = []
        try:
            resp = await self.httpx.get(url, headers={"Referer": f"{self.main_url}/"})
            sel = Selector(resp.text)

            # iframe[data-src] ve iframe[src]
            for iframe in sel.css("iframe[data-src], iframe[src]"):
                src = iframe.attrib.get("data-src") or iframe.attrib.get("src")
                if src and "about:blank" not in src:
                    embed_urls.append(self.fix_url(src))

            # Alternatif player / kaynak linkleri
            for player in sel.css("[data-video], [data-url], a.nav-link[data-src]"):
                src = player.attrib.get("data-video") or player.attrib.get("data-url") or player.attrib.get("data-src")
                if src and src not in embed_urls:
                    embed_urls.append(self.fix_url(src))

        except Exception as e:
            print(f"[!] {self.name} load_links hatası: {e}")

        return embed_urls

if __name__ == "__main__":
    import asyncio

    async def main():
        plugin = HDFilmCehennemi()
        test = await plugin.get_main_page(2)
        print(test[0])
        # await plugin.search("spider-Noir")
        # print((await plugin.load_item("https://www.hdfilmcehennemi.nl/worldbreaker-3/")).model_dump_json(indent=4))
        # await plugin.get_all_items()
        # print(await plugin.upload_all_İtem_to_database())
        await plugin.close()

    asyncio.run(main())