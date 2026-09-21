from typing import List, Union, Optional, Dict, Any
from parsel import Selector
import base64
import json
import random
import re
import string
import uuid
from Core.Plugin.PluginBase import PluginBase
from Core.Plugin.PluginModels import SearchResult, MainPageResult, MovieInfo, SeriesInfo
from Core.Helpers.TitleHelper import TitleHelper


class HDFilmCehennemi(PluginBase):
    """HDFilmCehennemi kaynak site kazıyıcısı."""

    name = "HDFilmCehennemi"
    language = "tr"
    main_url = "https://www.hdfilmcehennemi.nl"
    favicon = f"https://www.google.com/s2/favicons?domain={main_url}&sz=64"
    description = "Türkiye'nin en hızlı hd film izleme sitesi"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "X-Requested-With": "fetch",
        "Accept": "*/*",
        "Referer": f"{main_url}/",
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

    def __init__(self):
        super().__init__()
        self._extraction_data: Dict[str, Dict[str, Any]] = {}

    def generate_random_cookie(self) -> str:
        return "".join(random.choices(string.ascii_letters + string.digits, k=16))

    def generate_slug(self, title: str) -> str:
        slug = title.lower()
        slug = re.sub(r"[^a-z0-9]+", "-", slug)
        slug = slug.strip("-")
        return slug or str(uuid.uuid4())

    async def get_main_page(self, page: int = 1, url: str = "", category: str = "") -> list[MainPageResult]:
        if not url:
            url = f"{self.main_url}/load/page/{page}/home"

        request = await self.httpx.get(url, follow_redirects=True, headers=self.headers)
        if request.status_code != 200:
            return []

        try:
            data = request.json()
        except Exception:
            return []

        html = data.get("html")
        if not html or len(html) < 200:
            return []

        selector = Selector(text=html)

        return [
            MainPageResult(
                category=category,
                title=veri.css("strong.poster-title::text").get(),
                url=self.fix_url(veri.css("::attr(href)").get()),
                poster=self.fix_url(veri.css("img::attr(data-src)").get() or veri.css("img::attr(src)").get()),
                language=veri.css("div.poster-info > span.poster-lang > span::text").get().strip() if veri.css("div.poster-info > span.poster-lang > span::text").get() else None,
                release_date=veri.css("div.poster-meta > span::text").get().strip() if veri.css("div.poster-meta > span::text").get() else None,
                imdb=veri.css("div.poster-meta > span.imdb::text").get().strip() if veri.css("div.poster-meta > span.imdb::text").get() else None,
                plugin=self.name,
            )
            for veri in selector.css("a.poster")
        ]

    async def search(self, query: str) -> list[SearchResult]:
        request = await self.httpx.get(
            url=f"{self.main_url}/search?q={query}",
            headers={"Referer": f"{self.main_url}/", "X-Requested-With": "fetch", "authority": f"{self.main_url}"},
        )
        results = []
        for veri in request.json().get("results", []):
            secici = Selector(veri)
            title = secici.css("h4.title::text").get()
            href = secici.css("a::attr(href)").get()
            poster = secici.css("img::attr(data-src)").get() or secici.css("img::attr(src)").get()
            year = secici.css("span.year::text").get().strip() if secici.css("span.year::text").get() else None
            rating = secici.css("div.meta span.imdb::text").re_first(r"(\d+(?:\.\d+)?)")
            media_type = secici.css("div.meta span.type::text").get().strip() if secici.css("div.meta span.type::text").get() else "movie"
            if title and href:
                results.append(
                    SearchResult(
                        title=title.strip(),
                        url=self.fix_url(href.strip()),
                        poster=self.fix_url(poster.strip()) if poster else None,
                        year=year,
                        rating=rating,
                        plugin=self.name,
                        media_type=media_type
                    )
                )
        return results

    async def load_item(self, url: str) -> Optional[MovieInfo]:
        istek = await self.httpx.get(url, headers={"Referer": f"{self.main_url}/"})
        secici = Selector(istek.text)
        if "404 Hata - Sayfa Bulunamadı" in str(secici):
            return None

        try:
            title = secici.css("h1.section-title::text").get().strip()
            original_title = secici.css("h1.section-title small::text").get()

            if original_title:
                if original_title.split("(")[0].strip() != " ":
                    original_title = original_title.split("(")[0].strip()
                if original_title == "" and "-" in title:
                    original_title = title.split("-")[-1].strip()
                if original_title == "":
                    original_title = title
            else:
                original_title = title

            poster = (secici.css("aside.post-info-poster img::attr(data-src)").get() or secici.css("aside.post-info-poster img::attr(src)").get() or "").strip()
            description = secici.css("article.post-info-content > p::text").get().strip()
            genre = secici.css("div.post-info-genres a::text").getall()
            rating = secici.css("div.post-info-imdb-rating span::text").get().strip()
            vote_count_text = secici.css("div.post-info-imdb-rating small::text").get()
            vote_count = 0
            if vote_count_text:
                vote_count = int(vote_count_text.replace("(", "").replace(")", "").replace("oy", "").strip())
            year = secici.css("div.post-info-year-country a::text").getall()[0].strip() if secici.css("div.post-info-year-country a::text").getall() else None
            country = secici.css("div.post-info-year-country a::text").getall()[1].strip() if len(secici.css("div.post-info-year-country a::text").getall()) > 1 else None
            actors = secici.css("div.post-info-cast a > strong::text").getall()
            duration_text = secici.css("div.post-info-duration::text").get()
            duration = 0
            if duration_text:
                duration = int(duration_text.replace("dakika", "").strip())
            imdb = secici.css("div.post-info-imdb a::attr(data-id)").get().strip() if secici.css("div.post-info-imdb a::attr(data-id)").get() else None
            fragman = secici.css("div.post-info-trailer button::attr(data-modal)").get().strip() if secici.css("div.post-info-trailer button::attr(data-modal)").get() else None
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
            runtime_minutes=duration,
            imdb_id=imdb,
            fragman_url=fragman,
        )

        return data

    async def _get_cehennempass_links(self, video_id: str, referer: str) -> List[Dict[str, Any]]:
        """CehennemPass API'den video linklerini alır."""
        results = []
        for quality in ["low", "high"]:
            try:
                response = await self.httpx.post(
                    url="https://cehennempass.pw/process_quality_selection.php",
                    headers={
                        "Referer": f"https://cehennempass.pw/download/{video_id}",
                        "X-Requested-With": "fetch",
                        "authority": "cehennempass.pw",
                        "Cookie": f"PHPSESSID={self.generate_random_cookie()}",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                    data={"video_id": video_id, "selected_quality": quality},
                )
                data = response.json()
                video_url = data.get("download_link")
                if video_url:
                    video_url = self.fix_url(video_url)
                    self._extraction_data[video_url] = {
                        "name": f"{self.name} | {'Düşük' if quality == 'low' else 'Yüksek'} Kalite",
                        "referer": f"https://cehennempass.pw/download/{video_id}",
                        "headers": {
                            "User-Agent": self.headers["User-Agent"],
                            "Referer": f"https://cehennempass.pw/download/{video_id}",
                        },
                        "subtitles": []
                    }
                    results.append(self._extraction_data[video_url])
            except Exception as e:
                print(f"[!] CehennemPass {quality} kalite hatası: {e}")
        return results

    async def _unpack_packed_js(self, packed: str) -> str:
        """Dean Edwards Packer ile paketlenmiş JS'yi çözer."""
        pattern = r"}\('(.*?)'\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*'(.*?)'\.split\('\|'\)"
        match = re.search(pattern, packed, re.DOTALL)
        if not match:
            pattern_alt = r"eval\(function\(p,a,c,k,e,[rd]\)\{.*return p\}\('(.*?)'\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*'(.*?)'\.split\('\|'\)"
            match = re.search(pattern_alt, packed, re.DOTALL)
            if not match:
                return packed

        payload, radix, count, symtab = match.groups()
        radix = int(radix)
        count = int(count)
        words = symtab.split("|")

        def base_encode(num: int, b: int) -> str:
            chars = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
            if num == 0:
                return chars[0]
            res = []
            while num > 0:
                res.append(chars[num % b])
                num //= b
            return "".join(reversed(res))

        lookup = {}
        for i in range(count):
            key = base_encode(i, radix)
            lookup[key] = words[i] if i < len(words) and words[i] else key

        def replace_word(m):
            word = m.group(0)
            return lookup.get(word, word)

        return re.sub(r"\b\w+\b", replace_word, payload)

    async def _extract_from_iframe(self, iframe_url: str, source_name: str, referer: str) -> Optional[str]:
        """İframe sayfasından video URL'sini çıkarır."""
        self.httpx.headers.update({"Referer": f"{self.main_url}/"})

        try:
            resp = await self.httpx.get(iframe_url)
            html_content = resp.text

            # Packed JS kontrolü
            if "eval(function(p,a,c,k,e," in html_content:
                # CehennemPass pattern
                try:
                    video_id = iframe_url.split("/")[-1]
                    await self._get_cehennempass_links(video_id, referer)
                    return None
                except Exception:
                    pass

                # Normal packed JS unpack
                eval_func = re.compile(r'\s*(eval\(function[\s\S].*)\s*').findall(html_content)
                if eval_func:
                    unpacked = await self._unpack_packed_js(eval_func[0])
                    b64_match = re.search(r'file_link=\\"(.*?)\\"\;', unpacked)
                    if b64_match:
                        b64_url = b64_match.group(1)
                        video_url = base64.b64decode(b64_url).decode("utf-8")

                        # Altyazıları çıkar
                        subtitles = []
                        try:
                            sub_data = html_content.split("tracks: [")[1].split("]")[0]
                            for sub in re.findall(r'file":"([^"]+)".*?"language":"([^"]+)"', sub_data, flags=re.DOTALL):
                                subtitles.append({
                                    "name": sub[1].upper(),
                                    "url": self.fix_url(sub[0].replace("\\", "")),
                                })
                        except Exception:
                            pass

                        self._extraction_data[video_url] = {
                            "name": f"{self.name} | {source_name}",
                            "referer": referer,
                            "headers": {
                                "User-Agent": self.headers["User-Agent"],
                                "Referer": referer,
                            },
                            "subtitles": subtitles
                        }
                        return video_url
        except Exception as e:
            print(f"[!] İframe çıkarma hatası ({iframe_url}): {e}")

        return None

    async def load_links(self, url: str) -> List[str]:
        embed_urls = []
        self._extraction_data = {}

        try:
            resp = await self.httpx.get(url, headers={"Referer": f"{self.main_url}/"})
            sel = Selector(resp.text)

            # Alternatif linkler (ana video kaynakları)
            for alternatif in sel.css("div.alternative-links"):
                lang_code = alternatif.css("::attr(data-lang)").get()
                lang_code = lang_code.upper() if lang_code else ""

                for link in alternatif.css("button.alternative-link"):
                    source = f"{link.css('::text').get().replace('(HDrip Xbet)', '').strip()} {lang_code}".strip()
                    video_id = link.css("::attr(data-video)").get()

                    if not video_id:
                        continue

                    # Video API'sini çağır
                    try:
                        api_resp = await self.httpx.get(
                            url=f"{self.main_url}/video/{video_id}/",
                            headers={
                                "Content-Type": "application/json",
                                "X-Requested-With": "fetch",
                                "Referer": url,
                            },
                        )
                        api_data = api_resp.json()
                        html_content = api_data.get("data", {}).get("html", "")
                    except Exception:
                        html_content = api_resp.text if "api_resp" in locals() else ""

                    # iframe URL'sini çıkar (iframe class'ı Close/Rapidrame ayrımı için korunur)
                    src_match = re.search(r'data-src=["\']([^"\']+)["\']', html_content) or re.search(r'src=["\']([^"\']+)["\']', html_content)
                    if src_match:
                        iframe = src_match.group(1).replace(r"\/", "/").replace("\\", "")
                        # NOT: Close iframe'leri (?rapidrame_id= içerir) hdfilmcehennemi.mobi/video/embed/ adresini
                        # işaret eder ve kendine özgü closeplayer sayfası kullanır. Rapidrame iframe'leri
                        # doğrudan rplayer/{id}/ adresini işaret eder. Bu ikisini playerr/{id}/ adresine
                        # çevirmek Close iframe'inin yüklenememesine ve yalnızca Rapidrame kaynağının
                        # gelmesine neden olur. Bu yüzden olduğu gibi bırakıyoruz; extractor domain
                        # eşleştirmesi ile doğru çözümleyiciyi seçer.

                        # CehennemPass download sayfası ise
                        if "cehennempass.pw/download/" in iframe:
                            cehennem_id = iframe.split("/download/")[-1].split("?")[0]
                            await self._get_cehennempass_links(cehennem_id, url)
                            if iframe not in embed_urls:
                                embed_urls.append(iframe)
                        else:
                            fixed_iframe = self.fix_url(iframe)
                            if fixed_iframe not in embed_urls:
                                embed_urls.append(fixed_iframe)

            # Fallback: iframe[data-src] ve iframe[src]
            if not embed_urls:
                for iframe in sel.css("iframe[data-src], iframe[src]"):
                    src = iframe.attrib.get("data-src") or iframe.attrib.get("src")
                    if src and "about:blank" not in src:
                        fixed_src = self.fix_url(src)
                        if "cehennempass.pw/download/" in fixed_src:
                            cehennem_id = fixed_src.split("/download/")[-1].split("?")[0]
                            await self._get_cehennempass_links(cehennem_id, url)
                        if fixed_src not in embed_urls:
                            embed_urls.append(fixed_src)

            # Alternatif player / kaynak linkleri (yalnızca geçerli URL olanlar)
            for player in sel.css("a.nav-link[data-src], [data-url]"):
                src = player.attrib.get("data-src") or player.attrib.get("data-url")
                if src and ("http" in src or src.startswith("//") or "/embed" in src):
                    fixed_src = self.fix_url(src)
                    if fixed_src not in embed_urls:
                        embed_urls.append(fixed_src)

        except Exception as e:
            print(f"[!] {self.name} load_links hatası: {e}")

        return embed_urls

    def get_extraction_data(self, url: str) -> Optional[Dict[str, Any]]:
        """Extractor için ekstra veri sağlar."""
        return self._extraction_data.get(url)

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