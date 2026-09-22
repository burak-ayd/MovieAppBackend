import re
from typing import List, Union, Dict
from bs4 import BeautifulSoup
from Core.Plugin.PluginBase import PluginBase
from Core.Plugin.PluginModels import SearchResult, MainPageResult, MovieInfo, SeriesInfo, Episode
from Core.Helpers.TitleHelper import TitleHelper


class Dizilla(PluginBase):
    """Dizilla kaynak site kazıyıcısı (dizi odaklı)."""

    name = "Dizilla"
    language = "tr"
    main_url = "https://dizilla.now"
    description = "Dizilla - Türkçe dizi izleme sitesi"
    main_page = {
        "Son Bölümler": "/",
        "Popüler Diziler": "/populer-diziler/"
    }

    async def get_main_page(self, page: int, url: str, category: str) -> List[MainPageResult]:
        results = []
        try:
            full_url = f"{self.main_url}{url}"
            if page > 1:
                full_url = f"{full_url}page/{page}/"

            resp = await self.client.get(full_url)
            soup = BeautifulSoup(resp.text, "html.parser")

            items = soup.select("div.series-item, article.post, div.film-list div.item, div.episode-item")
            for item in items:
                a_tag = item.select_one("a[href]")
                img_tag = item.select_one("img")
                title_tag = item.select_one("h2, h3, .title, a")

                if not a_tag:
                    continue

                title = title_tag.get_text(strip=True) if title_tag else "Bilinmiyor"
                href = a_tag.get("href", "")
                poster = img_tag.get("data-src") or img_tag.get("src") if img_tag else None

                if not href.startswith("http"):
                    href = f"{self.main_url}{href}"

                results.append(MainPageResult(
                    title=title,
                    url=href,
                    category=category,
                    poster=poster,
                    provider=self.name
                ))
        except Exception as e:
            print(f"[!] {self.name} get_main_page hatası: {e}")

        return results

    async def search(self, query: str) -> List[SearchResult]:
        results = []
        try:
            search_url = f"{self.main_url}/arama/{query.replace(' ', '+')}/"
            resp = await self.client.get(search_url)
            soup = BeautifulSoup(resp.text, "html.parser")

            items = soup.select("div.series-item, article.post, div.film-list div.item")
            for item in items:
                a_tag = item.select_one("a[href]")
                img_tag = item.select_one("img")
                title_tag = item.select_one("h2, h3, .title, a")

                if not a_tag:
                    continue

                raw_title = title_tag.get_text(strip=True) if title_tag else "Bilinmiyor"
                cleaned_title, year = TitleHelper.clean(raw_title)
                href = a_tag.get("href", "")
                poster = img_tag.get("data-src") or img_tag.get("src") if img_tag else None

                if not href.startswith("http"):
                    href = f"{self.main_url}{href}"

                results.append(SearchResult(
                    title=cleaned_title,
                    url=href,
                    poster=poster,
                    provider=self.name,
                    year=year,
                    media_type="tv"
                ))
        except Exception as e:
            print(f"[!] {self.name} search hatası: {e}")

        return results

    async def load_item(self, url: str) -> Union[MovieInfo, SeriesInfo]:
        try:
            resp = await self.client.get(url)
            soup = BeautifulSoup(resp.text, "html.parser")

            title_tag = soup.select_one("h1, h2.series-title, div.series-title")
            raw_title = title_tag.get_text(strip=True) if title_tag else "Bilinmiyor"
            cleaned_title, _ = TitleHelper.clean(raw_title)

            img_tag = soup.select_one("div.series-poster img, div.poster img, img.series-poster")
            poster = img_tag.get("data-src") or img_tag.get("src") if img_tag else None

            desc_tag = soup.select_one("div.series-description, div.description, p.description")
            description = desc_tag.get_text(strip=True) if desc_tag else None

            # Sezon/Bölüm bilgilerini çıkar
            seasons: Dict[int, List[Episode]] = {}
            season_sections = soup.select("div.season-list, div.seasons, ul.season")
            for section in season_sections:
                season_num_tag = section.select_one("[data-season], .season-number, h3")
                if season_num_tag:
                    season_text = season_num_tag.get("data-season") or season_num_tag.get_text()
                    season_match = re.search(r'(\d+)', str(season_text))
                    season_num = int(season_match.group(1)) if season_match else 1
                else:
                    season_num = 1

                episodes = []
                ep_items = section.select("a[href], li a")
                for i, ep in enumerate(ep_items, 1):
                    ep_href = ep.get("href", "")
                    ep_title = ep.get_text(strip=True)
                    if not ep_href.startswith("http"):
                        ep_href = f"{self.main_url}{ep_href}"
                    episodes.append(Episode(
                        season_number=season_num,
                        episode_number=i,
                        title=ep_title,
                        url=ep_href
                    ))
                if episodes:
                    seasons[season_num] = episodes

            return SeriesInfo(
                title=cleaned_title,
                url=url,
                provider=self.name,
                poster=poster,
                seasons=seasons,
                description=description
            )
        except Exception as e:
            print(f"[!] {self.name} load_item hatası: {e}")
            return SeriesInfo(title="Hata", url=url, provider=self.name)

    async def load_links(self, url: str) -> List[str]:
        embed_urls = []
        try:
            resp = await self.client.get(url)
            soup = BeautifulSoup(resp.text, "html.parser")

            # iframe src'lerini topla
            iframes = soup.select("iframe[src]")
            for iframe in iframes:
                src = iframe.get("src", "")
                if src and "about:blank" not in src:
                    if src.startswith("//"):
                        src = f"https:{src}"
                    embed_urls.append(src)

            # data attributelarından URL çıkar
            players = soup.select("[data-src], [data-url], [data-video]")
            for player in players:
                data_url = player.get("data-src") or player.get("data-url") or player.get("data-video")
                if data_url and data_url not in embed_urls:
                    if data_url.startswith("//"):
                        data_url = f"https:{data_url}"
                    embed_urls.append(data_url)

        except Exception as e:
            print(f"[!] {self.name} load_links hatası: {e}")

        return embed_urls
