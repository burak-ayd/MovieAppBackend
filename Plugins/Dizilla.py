# Oluşturan: Burak Aydoğan

import asyncio
import base64
import json
import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

from bs4 import BeautifulSoup
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from Core.Plugin.PluginBase import PluginBase
from Core.Plugin.PluginModels import Episode, MainPageResult, MovieInfo, SearchResult, SeriesInfo
from Core.Helpers.EmbedHelper import EmbedHelper
from Core.Helpers.TitleHelper import TitleHelper


class Dizilla(PluginBase):
    """Dizilla kaynak site kazıyıcısı (Dizi odaklı, AES-CBC API ve secureData desteği).

    Kotlin (cloudstream3) karşılıkları:
        * ``mainPage``            -> ``main_page``
        * ``getMainPage``         -> ``get_main_page``   (3 dal: arsiv / findSeries API / HTML)
        * ``search`` / ``quickSearch`` -> ``search``
        * ``load``                -> ``load_item``       (sezon sayfaları dahil)
        * ``loadLinks``           -> ``load_links``      (source_content -> iframe)
        * ``fixPosterUrl``        -> ``fix_poster_url``
        * ``decryptDizillaResponse`` -> ``_decrypt_dizilla_response``
        * ``CloudflareInterceptor``  -> ``_fetch_text`` (CF challenge yakalanınca Playwright'a düşer)

    Notlar:
        * Site Next.js tabanlıdır. Liste verisi sayfa içindeki ``script#__NEXT_DATA__``
          -> ``props.pageProps.secureData`` alanında AES-CBC/PKCS5 ile şifrelenmiş gelir.
        * Kategori listeleri ``/api/bg/*`` uç noktalarından POST ile alınır; yanıttaki
          ``response`` alanı aynı anahtarla çözülür.
    """

    name = "Dizilla"
    language = "tr"
    main_url = "https://dizilla.now"
    description = "Dizilla - Yabancı dizi izleme platformu"
    favicon = f"https://www.google.com/s2/favicons?domain={main_url}&sz=256"

    # Kotlin: private val privateAESKey / IvParameterSpec(ByteArray(16)) / AES-CBC-PKCS5Padding
    _private_aes_key = b"9bYMCNQiWsXIYFWYAu7EkdsSbmGBTyUI"
    _aes_iv = bytes(16)

    # Kotlin: sequentialMainPageDelay = 150L (0.15 saniye)
    sequential_delay = 0.15
    # "Yeni Eklenen Bölümler" kategorisinde kaç günlük pencere taranacağı
    episode_window_days = 45
    request_timeout = 30

    # Sezon sayfası URL kalıbı (dizi sayfasında değil -> ilk bölüme inilir)
    _season_url_re = re.compile(r"-\d+-sezon-c\d+", re.IGNORECASE)

    # Poster doğrulama önbelleği: {url: erişilebilir mi}. Sınıf seviyesinde tutulur ki
    # aynı CDN adresi farklı sayfalarda tekrar tekrar HEAD isteğiyle sorgulanmasın.
    _poster_cache: Dict[str, bool] = {}

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:137.0) Gecko/20100101 Firefox/137.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    api_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:137.0) Gecko/20100101 Firefox/137.0",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.5",
        "X-Requested-With": "XMLHttpRequest",
    }

    main_page = {
        "Ana Sayfa": main_url,
        "Yeni Eklenen Bölümler": f"{main_url}/tum-bolumler",
        "Yeni Eklenen Diziler": f"{main_url}/arsiv",
        "Aile": f"{main_url}/api/bg/findSeries?releaseYearStart=1900&releaseYearEnd=2024&imdbPointMin=5&imdbPointMax=10&categoryIdsComma=15&countryIdsComma=&orderType=date_desc&languageId=-1&currentPage=1&currentPageCount=24&queryStr=&categorySlugsComma=&countryCodesComma=",
        "Aksiyon": f"{main_url}/api/bg/findSeries?releaseYearStart=1900&releaseYearEnd=2024&imdbPointMin=5&imdbPointMax=10&categoryIdsComma=9&countryIdsComma=&orderType=date_desc&languageId=-1&currentPage=1&currentPageCount=24&queryStr=&categorySlugsComma=&countryCodesComma=",
        "Bilim Kurgu": f"{main_url}/api/bg/findSeries?releaseYearStart=1900&releaseYearEnd=2024&imdbPointMin=5&imdbPointMax=10&categoryIdsComma=5&countryIdsComma=&orderType=date_desc&languageId=-1&currentPage=1&currentPageCount=24&queryStr=&categorySlugsComma=&countryCodesComma=",
        "Dram": f"{main_url}/api/bg/findSeries?releaseYearStart=1900&releaseYearEnd=2024&imdbPointMin=5&imdbPointMax=10&categoryIdsComma=2&countryIdsComma=&orderType=date_desc&languageId=-1&currentPage=1&currentPageCount=24&queryStr=&categorySlugsComma=&countryCodesComma=",
        "Fantastik": f"{main_url}/api/bg/findSeries?releaseYearStart=1900&releaseYearEnd=2024&imdbPointMin=5&imdbPointMax=10&categoryIdsComma=12&countryIdsComma=&orderType=date_desc&languageId=-1&currentPage=1&currentPageCount=24&queryStr=&categorySlugsComma=&countryCodesComma=",
        "Gerilim": f"{main_url}/api/bg/findSeries?releaseYearStart=1900&releaseYearEnd=2024&imdbPointMin=5&imdbPointMax=10&categoryIdsComma=18&countryIdsComma=&orderType=date_desc&languageId=-1&currentPage=1&currentPageCount=24&queryStr=&categorySlugsComma=&countryCodesComma=",
        "Komedi": f"{main_url}/api/bg/findSeries?releaseYearStart=1900&releaseYearEnd=2024&imdbPointMin=5&imdbPointMax=10&categoryIdsComma=4&countryIdsComma=&orderType=date_desc&languageId=-1&currentPage=1&currentPageCount=24&queryStr=&categorySlugsComma=&countryCodesComma=",
        "Korku": f"{main_url}/api/bg/findSeries?releaseYearStart=1900&releaseYearEnd=2024&imdbPointMin=5&imdbPointMax=10&categoryIdsComma=8&countryIdsComma=&orderType=date_desc&languageId=-1&currentPage=1&currentPageCount=24&queryStr=&categorySlugsComma=&countryCodesComma=",
        "Macera": f"{main_url}/api/bg/findSeries?releaseYearStart=1900&releaseYearEnd=2024&imdbPointMin=5&imdbPointMax=10&categoryIdsComma=24&countryIdsComma=&orderType=date_desc&languageId=-1&currentPage=1&currentPageCount=24&queryStr=&categorySlugsComma=&countryCodesComma=",
        "Romantik": f"{main_url}/api/bg/findSeries?releaseYearStart=1900&releaseYearEnd=2024&imdbPointMin=5&imdbPointMax=10&categoryIdsComma=7&countryIdsComma=&orderType=date_desc&languageId=-1&currentPage=1&currentPageCount=24&queryStr=&categorySlugsComma=&countryCodesComma=",
    }

    # ================================================================== #
    # Yardımcılar
    # ================================================================== #

    def fix_poster_url(self, url: Optional[str]) -> Optional[str]:
        """Kotlin'deki fixPosterUrl: AMP CDN adreslerini kaynak domain'e çevirir.

        https://x.cdn.ampproject.org/i/s/images.macellan.online/... -> https://images.macellan.online/...
        """
        if not url:
            return url

        if "cdn.ampproject.org" in url:
            match = re.search(r"cdn\.ampproject\.org/[^/]+/s/(.+)$", url)
            if match:
                return f"https://{match.group(1)}"

        return url

    def _poster_variants(self, url: Optional[str]) -> List[str]:
        """Aynı görselin CDN üzerindeki olası yol biçimlerini deneme sırasıyla döner.

        Site aynı görseli iki farklı biçimde dağıtıyor ve API'deki yol her zaman çalışmıyor:

            https://images-macellan-online.cdn.ampproject.org/i/s/images.macellan.online/images/tv/poster/...   ✅
            https://file.macellan.online/images/f/f/100//<dosya>                                              ❌ 404
            https://file.macellan.online/images/280/420/65//<dosya>        (sitenin kullandığı yol)             ✅
            https://images.macellan.online/images/tv/poster/f/f/100/<dosya>  (b47b8... hash'li dosyalar)        ✅

        Bu yüzden `file.macellan.online` adreslerinde önce sitenin kendi boyut yolu denenir,
        doğrulama (_resolve_poster) başarısız olursa diğer biçimlere düşülür.
        """
        base = self.fix_poster_url(url) if url else None
        if not base:
            return []

        file_name = base.rsplit("/", 1)[-1]
        variants = [base]

        if "file.macellan.online" in base and "." in file_name:
            variants = [
                f"https://file.macellan.online/images/280/420/65/{file_name}",
                f"https://images.macellan.online/images/tv/poster/f/f/100/{file_name}",
                f"https://file.macellan.online/images/280/420/100/{file_name}",
                base,
            ]

        return variants

    async def _image_ok(self, url: str) -> bool:
        """URL'nin gerçekten bir görsel döndürdüğünü HEAD ile doğrular (sonuçlar önbelleklenir)."""
        if not url:
            return False

        cached = self._poster_cache.get(url)
        if cached is not None:
            return cached

        ok = False
        try:
            resp = await self.client.head(
                url,
                headers=self._page_headers(),
                timeout=10,
                follow_redirects=True,
            )
            ok = resp.status_code == 200 and resp.headers.get("content-type", "").startswith("image/")
        except Exception:
            ok = False

        if len(self._poster_cache) > 5000:  # bellek taşmasını önle
            self._poster_cache.clear()
        self._poster_cache[url] = ok

        return ok

    async def _resolve_poster(self, *raw_urls: Optional[str]) -> Optional[str]:
        """Verilen alanlardan ilk gerçekten erişilebilir poster URL'sini döner.

        Hiçbiri doğrulanamazsa ilk adayı döner (davranış eski hâlden daha kötü olmaz).
        """
        candidates: List[str] = []
        for raw in raw_urls:
            for variant in self._poster_variants(raw):
                if variant not in candidates:
                    candidates.append(variant)

        if not candidates:
            return None

        for candidate in candidates:
            if await self._image_ok(candidate):
                return candidate

        return candidates[0]

    async def _resolve_posters(self, items: List[Dict[str, Any]], *fields: str) -> List[Optional[str]]:
        """Sayfa içindeki tüm posterleri paralel doğrular (24 kartlık sayfada seri kontrol yapılırsa yavaşlar)."""
        return list(await asyncio.gather(*(self._resolve_poster(*(item.get(f) for f in fields)) for item in items)))

    def _decrypt_dizilla_response(self, encrypted_b64: str) -> Optional[str]:
        """Kotlin'deki decryptDizillaResponse metodunun AES-CBC/PKCS5 karşılığı."""
        if not encrypted_b64:
            return None

        try:
            full_data = base64.b64decode(encrypted_b64)
            cipher = Cipher(algorithms.AES(self._private_aes_key), modes.CBC(self._aes_iv))
            decryptor = cipher.decryptor()
            padded_data = decryptor.update(full_data) + decryptor.finalize()

            # PKCS5 == PKCS7 (AES blok boyutu 16 byte)
            unpadder = padding.PKCS7(128).unpadder()
            decrypted_bytes = unpadder.update(padded_data) + unpadder.finalize()
            return decrypted_bytes.decode("utf-8")
        except Exception as e:
            print(f"[!] {self.name} Decryption hatası: {e}")
            return None

    @staticmethod
    def _loads(decoded: str) -> Optional[Dict[str, Any]]:
        """Çözülmüş metni JSON'a çevirir; bozuk gelen başlangıcı onarır (Kotlin'deki `{"m` tamiri)."""
        if not decoded:
            return None

        text = decoded.strip()
        # Bazı yanıtlarda JSON başlığı (ör. `{"message"`) eksik geliyor; Kotlin'deki `{"m` tamiri
        if not text.startswith("{"):
            if re.match(r'^essage"', text):
                text = '{"m' + text
            elif re.match(r'^message"', text):
                text = "{" + text

        try:
            data = json.loads(text)
        except Exception:
            return None

        return data if isinstance(data, dict) else None

    @staticmethod
    def _extract_result_array(decoded: str) -> List[Dict[str, Any]]:
        """`"result":[ ... ]` dizisini döndürür.

        JSON bütün olarak çözülemiyorsa Kotlin'deki parantez sayacı ile manuel ayıklamaya düşer
        (şifreli veri bazen eksik/bozuk geldiği için Jackson bu yola düşüyordu).
        """
        if not decoded:
            return []

        data = Dizilla._loads(decoded)
        if data and isinstance(data.get("result"), list):
            return data["result"]

        match = re.search(r'"result"\s*:\s*\[', decoded)
        if not match:
            return []

        start = match.end() - 1  # "[" karakterinin indeksi
        depth = 0
        in_string = False
        escaped = False

        for i in range(start, len(decoded)):
            char = decoded[i]

            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    try:
                        array = json.loads(decoded[start:i + 1])
                    except Exception:
                        return []
                    return array if isinstance(array, list) else []

        return []

    @staticmethod
    def _is_cf_challenge(text: str) -> bool:
        """Cloudflare doğrulama sayfası mı? (Kotlin: doc.html().contains("verifying"))"""
        head = (text or "")[:20000].lower()
        return any(marker in head for marker in (
            "just a moment",
            "cf-browser-verification",
            "challenge-platform",
            "cf_chl_opt",
            "checking your browser",
            "verifying",
        ))

    def _page_headers(self, referer: Optional[str] = None, api: bool = False) -> Dict[str, str]:
        headers = dict(self.api_headers if api else self.headers)
        headers["Referer"] = referer or f"{self.main_url}/"
        return headers

    async def _fetch_text(self, url: str, referer: Optional[str] = None) -> str:
        """Sayfayı çeker; Cloudflare koruması varsa Playwright tabanlı çözüme düşer."""
        text = ""
        try:
            resp = await self.client.get(
                url,
                headers=self._page_headers(referer),
                timeout=self.request_timeout,
                follow_redirects=True,
            )
            text = resp.text or ""
            if resp.status_code == 200 and not self._is_cf_challenge(text):
                return text
        except Exception as e:
            print(f"[!] {self.name} GET hatası ({url}): {e}")

        try:
            return await self.async_cf_get(url, headers=self._page_headers(referer))
        except Exception as e:
            print(f"[!] {self.name} Cloudflare aşılamadı ({url}): {e}")

        return text

    async def _api_decrypt(
        self,
        url: str,
        referer: Optional[str] = None,
        data: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """POST /api/bg/* uç noktasını çağırıp şifreli `response` alanını çözerek metni döner."""
        headers = self._page_headers(referer or self.main_url, api=True)
        headers["Origin"] = self.main_url
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"

        try:
            resp = await self.client.post(
                url,
                params=params,
                data=data,
                headers=headers,
                timeout=self.request_timeout,
                follow_redirects=True,
            )
            if resp.status_code != 200:
                print(f"[!] {self.name} API {resp.status_code}: {url}")
                return None
            payload = resp.json()
        except Exception as e:
            print(f"[!] {self.name} API hatası ({url}): {e}")
            return None

        if not payload.get("success"):
            return None

        blob = payload.get("response")
        if not blob:
            return None

        return self._decrypt_dizilla_response(blob)

    def _secure_text(self, html: str) -> Optional[str]:
        """__NEXT_DATA__ -> props.pageProps.secureData -> çözülmüş metin."""
        soup = BeautifulSoup(html or "", "html.parser")
        node = soup.select_one("script#__NEXT_DATA__")
        if not node or not node.string:
            return None

        try:
            root = json.loads(node.string)
        except Exception:
            return None

        page_props = (root.get("props") or {}).get("pageProps") or {}
        secure_data = page_props.get("secureData")
        if not secure_data:
            return None

        return self._decrypt_dizilla_response(secure_data)

    def _secure_payload(self, html: str) -> Dict[str, Any]:
        """`_secure_text` sonucunu JSON sözlüğüne çevirir."""
        return self._loads(self._secure_text(html) or "") or {}

    @staticmethod
    def _clean_title(raw: str) -> Tuple[Optional[str], Optional[int]]:
        """TitleHelper.clean tek değer ya da (metin, yıl) döndürebiliyor; ikisini de destekler."""
        text = (raw or "").strip()
        if not text:
            return None, None

        year_match = re.search(r"\b(19\d{2}|20\d{2})\b", text)
        year = int(year_match.group(1)) if year_match else None

        try:
            cleaned = TitleHelper.clean(text)
        except Exception:
            cleaned = text

        if isinstance(cleaned, tuple):
            cleaned, helper_year = cleaned[0], cleaned[1]
            year = year or (int(helper_year) if helper_year else None)

        return (cleaned or text), year

    @staticmethod
    def _series_slug(item: Dict[str, Any]) -> str:
        """Kotlin'deki `"serie_site_id":0,.*?"used_slug":"(.*?)"` regex'inin güvenli karşılığı."""
        slug = item.get("used_slug") or item.get("slug") or ""
        if slug:
            return str(slug).strip("/")

        try:
            raw = json.dumps(item, ensure_ascii=False)
        except Exception:
            return ""

        match = re.search(r'"serie_site_id":0,.*?"used_slug":"(.*?)"', raw)
        return match.group(1) if match else ""

    @staticmethod
    def _season_number(href: str) -> Optional[int]:
        match = re.search(r"-(\d+)-sezon", href or "", re.IGNORECASE)
        return int(match.group(1)) if match else None

    @staticmethod
    def _episode_number(value: str) -> Optional[int]:
        value = (value or "").strip()
        if value.isdigit():
            return int(value)
        match = re.search(r"-(\d+)-bolum", value, re.IGNORECASE)
        return int(match.group(1)) if match else None

    # ================================================================== #
    # Ana sayfa / kategoriler
    # ================================================================== #

    async def get_main_page(self, page: int = 1, url: str = "", category: str = "") -> List[MainPageResult]:
        """Kotlin getMainPage: arşiv, findSeries API ya da ham HTML dalına yönlendirir."""
        data = (url or "").strip() or self.main_url
        page = max(1, int(page or 1))

        try:
            if data.rstrip("/") == self.main_url.rstrip("/"):
                results = await self._home_page(category)
            elif "api/bg/findSeries" in data:
                results = await self._find_series_page(page, data, category)
            elif "/arsiv" in data:
                results = await self._archive_page(page, category)
            elif "tum-bolumler" in data:
                results = await self._episodes_page(page, category)
            else:
                results = await self._html_page(page, data, category)
        except Exception as e:
            print(f"[!] {self.name} get_main_page hatası: {e}")
            return []

        # Aynı URL'yi iki kez ekleme (dublaj/altyazı tekrarları olabiliyor)
        unique: List[MainPageResult] = []
        seen = set()
        for item in results:
            if not item.url or item.url in seen:
                continue
            seen.add(item.url)
            unique.append(item)

        return unique

    async def _find_series_page(self, page: int, api_url: str, category: str) -> List[MainPageResult]:
        """Kotlin: `api/bg/findSeries` -> POST -> decrypt -> "result" dizisi."""
        target = re.sub(r"currentPage=\d+", f"currentPage={page}", api_url)

        # Not: Kotlin gövdeye `page` gönderiyor; gerçek sayfalayıcı query'deki currentPage.
        decoded = await self._api_decrypt(target, data={"page": str(page)})
        items = self._extract_result_array(decoded or "")
        results: List[MainPageResult] = []

        titles: List[Optional[str]] = []
        slugs: List[str] = []
        for item in items:
            titles.append(
                item.get("original_title")
                or item.get("culture_title")
                or item.get("title")
                or item.get("used_title")
            )
            slugs.append(self._series_slug(item))

        posters = await self._resolve_posters(items, "poster_url", "square_url", "face_url", "back_url")

        for index, item in enumerate(items):
            title, slug = titles[index], slugs[index]
            if not title or not slug:
                continue

            year = item.get("release_year") or item.get("object_release_year")

            results.append(MainPageResult(
                title=str(title).strip(),
                url=self.fix_url(f"/{slug}"),
                category=category or "Diziler",
                poster=posters[index],
                release_date=str(year) if year else item.get("release_date"),
                rating=str(item.get("imdb_point")) if item.get("imdb_point") else None,
                plugin=self.name,
            ))

        return results

    async def _archive_page(self, page: int, category: str) -> List[MainPageResult]:
        """Kotlin: `/arsiv` -> __NEXT_DATA__ -> secureData -> `listItems`."""
        if page > 1:
            # Site `?page=` parametresini yok sayıyor; aynı "tarih sıralı diziler" listesinin
            # sayfalı hali için findSeries API'sine düşülüyor.
            return await self._find_series_page(page, self._all_series_api_url(page), category)

        html = await self._fetch_text(f"{self.main_url}/arsiv?page={page}")
        payload = self._secure_payload(html)
        list_items = [i for i in (payload.get("listItems") or []) if isinstance(i, dict)]
        results: List[MainPageResult] = []

        titles: List[Optional[str]] = []
        slugs: List[str] = []
        for item in list_items:
            titles.append(item.get("original_title") or item.get("used_title"))
            slugs.append(self._series_slug(item))

        posters = await self._resolve_posters(list_items, "poster_url", "square_url", "face_url", "back_url")

        for index, item in enumerate(list_items):
            title, slug = titles[index], slugs[index]
            if not title or not slug:
                continue

            year = item.get("release_year")

            results.append(MainPageResult(
                title=str(title).strip(),
                url=self.fix_url(f"/{slug}"),
                category=category or "Yeni Eklenen Diziler",
                poster=posters[index],
                release_date=str(year) if year else item.get("update_date"),
                rating=str(item.get("imdb_point")) if item.get("imdb_point") else None,
                plugin=self.name,
            ))

        return results

    async def _episodes_page(self, page: int, category: str) -> List[MainPageResult]:
        """Kotlin'un `div.col-span-3 a` (sonBolumler) dalı.

        Sayfa istemci tarafında render edildiği için HTML seçicileri boş dönüyor; sitenin
        kendi kullandığı `getepisodesonbrandbetweendate` ucu kullanılıyor. Başlık biçimi
        Kotlin ile aynı: "Dizi Adı - 1x02".
        """
        today = date.today()
        params = {
            "curPage": page,
            "curLength": 24,
            "languageId": "2,3,4",
            "typeId": 0,
            "minDate": (today - timedelta(days=self.episode_window_days)).isoformat(),
            "maxDate": (today + timedelta(days=1)).isoformat(),
        }

        decoded = await self._api_decrypt(
            f"{self.main_url}/api/bg/getepisodesonbrandbetweendate",
            referer=f"{self.main_url}/tum-bolumler",
            params=params,
        )

        results: List[MainPageResult] = []
        items = self._extract_result_array(decoded or "")
        posters = await self._resolve_posters(items, "poster_url", "square_url", "face_url", "back_url")

        for index, item in enumerate(items):
            name = item.get("original_title") or item.get("culture_title")
            slug = str(item.get("episode_used_slug") or "").strip("/")
            if not name or not slug:
                continue

            season_no = item.get("season_no") or 1
            episode_no = item.get("episode_no") or 1

            results.append(MainPageResult(
                title=f"{str(name).strip()} - {season_no}x{episode_no}",
                # Bölüm linki döneriz; load_item bu linkten dizi sayfasını çözümler.
                url=self.fix_url(f"/{slug}"),
                category=category or "Yeni Eklenen Bölümler",
                poster=posters[index],
                release_date=item.get("release_date"),
                rating=str(item.get("imdb_point")) if item.get("imdb_point") else None,
                plugin=self.name,
            ))

        return results

    async def _home_page(self, category: str = "") -> List[MainPageResult]:
        """Ana sayfa: bölüm bloklarındaki (`h2` başlıklı grid'ler) dizi kartları.

        Kök sayfada `?page=` çalışmaz; her bölüm kendi sabit listesini gösterir.
        """
        html = await self._fetch_text(self.main_url)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        results: List[MainPageResult] = []

        for anchor in soup.select('a[href^="/dizi/"][title]'):
            href = anchor.get("href") or ""
            if not href:
                continue

            # Bölüm adı: karttan önce gelen en yakın h2
            bolum = ""
            for onceki in anchor.find_all_previous(["h2"], limit=1):
                bolum = (onceki.get_text(strip=True) or "")[:60]

            baslik = (anchor.get("title") or "").replace(" izle", "").strip()
            if not baslik:
                baslik_tag = anchor.select_one("h3")
                baslik = baslik_tag.get_text(strip=True) if baslik_tag else ""
            if not baslik:
                continue

            poster_tag = anchor.select_one("img")
            poster = None
            if poster_tag:
                poster = poster_tag.get("src") or poster_tag.get("data-src")
                poster = self.fix_url(poster) if poster else None

            # Yıl: `span.text-white` (ör. "2026"), yoksa `img alt` içindeki yıl
            yil = None
            yil_tag = anchor.select_one("span.text-white")
            if yil_tag:
                m = re.search(r"\b(19\d{2}|20\d{2})\b", yil_tag.get_text(strip=True))
                yil = int(m.group(1)) if m else None
            if yil is None:
                m = re.search(r"\b(19\d{2}|20\d{2})\b", anchor.get("alt") or "")
                yil = int(m.group(1)) if m else None

            # Puan: `h4` (ör. "7.7")
            puan = None
            puan_tag = anchor.select_one("h4")
            if puan_tag:
                m = re.search(r"\d+[.,]\d+", puan_tag.get_text(strip=True))
                puan = m.group(0).replace(",", ".") if m else None

            results.append(MainPageResult(
                title        = baslik,
                url          = self.fix_url(href),
                category     = category or bolum,
                poster       = poster,
                release_date = str(yil) if yil else None,
                rating       = puan,
            ))

        return results

    async def _html_page(self, page: int, url: str, category: str) -> List[MainPageResult]:
        """Kotlin'un kalan HTML dalı: `span.watchlistitem-` (diziler) / `div.col-span-3 a` (son bölümler)."""
        target = self.fix_url(url)
        if page > 1 and "?" not in target:
            target = f"{target}?page={page}"

        html = await self._fetch_text(target)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        results: List[MainPageResult] = []

        if "api" in target:
            for element in soup.select("span.watchlistitem-"):
                results.append(self._watchlist_item(element, category))
        else:
            for element in soup.select("div.col-span-3 a"):
                item = await self._latest_episode_item(element, category)
                if item:
                    results.append(item)

        return results

    def _watchlist_item(self, element, category: str) -> Optional[MainPageResult]:
        """Kotlin'deki Element.diziler()."""
        anchor = element.select_one("a[href]")
        if not anchor:
            return None

        title_tag = element.select_one("span.font-normal")
        image = element.select_one("img")
        poster = image.get("src") or image.get("data-src") if image else None

        return MainPageResult(
            title=title_tag.get_text(strip=True) if title_tag else None,
            url=self.fix_url(anchor.get("href")),
            category=category or "Diziler",
            poster=self.fix_poster_url(self.fix_url(poster)) if poster else None,
            plugin=self.name,
        )

    async def _latest_episode_item(self, element, category: str) -> Optional[MainPageResult]:
        """Kotlin'deki Element.sonBolumler(): başlık + bölüm bilgisi, link için sayfa ziyareti."""
        href = element.get("href")
        if not href:
            return None

        name_tag = element.select_one("h2")
        episode_tag = element.select_one("div.opacity-80")
        name = name_tag.get_text(strip=True) if name_tag else ""
        episode_text = episode_tag.get_text(strip=True).replace(". Sezon ", "x").replace(". Bölüm", "") if episode_tag else ""
        title = f"{name} - {episode_text}".strip(" -")

        await asyncio.sleep(self.sequential_delay)
        html = await self._fetch_text(self.fix_url(href))
        if not html:
            return None

        episode_soup = BeautifulSoup(html, "html.parser")
        series_anchor = episode_soup.select_one("div.poster a[href]") or episode_soup.select_one('a[href^="/dizi/"]')
        if not series_anchor:
            return None

        poster_tag = episode_soup.select_one("div.poster img")
        raw_poster = poster_tag.get("src") or poster_tag.get("data-src") if poster_tag else None

        return MainPageResult(
            title=title,
            url=self.fix_url(series_anchor.get("href")),
            category=category or "Yeni Eklenen Bölümler",
            poster=await self._resolve_poster(raw_poster),
            plugin=self.name,
        )

    def _all_series_api_url(self, page: int = 1) -> str:
        """Tarih sıralı, kategorisiz dizi listesi (arsiv sayfasının sayfalı karşılığı)."""
        return (
            f"{self.main_url}/api/bg/findSeries?releaseYearStart=1900&releaseYearEnd=2024"
            f"&imdbPointMin=5&imdbPointMax=10&categoryIdsComma=&countryIdsComma=&orderType=date_desc"
            f"&languageId=-1&currentPage={page}&currentPageCount=24&queryStr="
            f"&categorySlugsComma=&countryCodesComma="
        )

    async def get_random(self, count: int = 3) -> List[MainPageResult]:
        """Rastgele *dizi* kartı seçer (ana sayfa bölüm linkleri verdiği için)."""
        import random

        series_categories = [(name, url) for name, url in self.main_page.items() if name != "Yeni Eklenen Bölümler"]
        random.shuffle(series_categories)

        items: List[MainPageResult] = []
        for name, url in series_categories[:3]:
            try:
                page_items = await self.get_main_page(page=random.randint(1, 3), url=url, category=name)
            except Exception:
                continue
            items.extend(item for item in page_items if item.url and "/dizi/" in item.url)
            if len(items) >= count * 2:
                break

        unique = list({item.url: item for item in items if item.url}.values())
        if not unique:
            return await super().get_random(count=count)

        return unique if len(unique) <= count else random.sample(unique, count)

    # ================================================================== #
    # Arama
    # ================================================================== #

    async def search(self, query: str) -> List[SearchResult]:
        """Kotlin search() implementasyonu: API POST isteği ve AES JSON deşifreleme."""
        results = []
        try:
            api_url = f"{self.main_url}/api/bg/searchContent?searchterm={query}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:137.0) Gecko/20100101 Firefox/137.0",
                "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{self.main_url}/"
            }

            resp = await self.client.post(api_url, headers=headers, timeout=self.request_timeout)
            json_resp = resp.json()

            encrypted_blob = json_resp.get("response")
            if not encrypted_blob:
                return results

            decrypted_json_str = self._decrypt_dizilla_response(encrypted_blob)
            if not decrypted_json_str:
                return results

            # Kotlin kodundaki bozuk JSON başlangıç düzeltmesi: {"m...
            if not decrypted_json_str.startswith("{") and '"essage"' in decrypted_json_str:
                decrypted_json_str = '{"m' + decrypted_json_str

            data = json.loads(decrypted_json_str)
            if not data.get("state"):
                return results

            items = data.get("result", [])
            # Poster adresleri CDN'de iki farklı biçimde geliyor; hepsini paralel doğrula.
            posters = await self._resolve_posters(
                items, "poster", "object_poster_url", "object_square_url", "object_face_url", "object_back_url"
            )

            for index, item in enumerate(items):
                raw_title = str(item.get("title") or item.get("object_name") or "")
                slug = str(item.get("slug") or item.get("used_slug") or "")
                raw_year = item.get("release_year") or item.get("object_release_year")

                cleaned_title, year = self._clean_title(raw_title)
                if not year and raw_year:
                    try:
                        year = int(raw_year)
                    except (ValueError, TypeError):
                        year = None

                link = self.fix_url(slug)
                poster_url = posters[index]

                results.append(SearchResult(
                    title=cleaned_title or raw_title,
                    url=link,
                    poster=poster_url,
                    year=year,
                    media_type= "Dizi",
                    plugin=self.name
                ))
        except Exception as e:
            print(f"[!] {self.name} search hatası: {e}")

        return results

    # ================================================================== #
    # İçerik detayı
    # ================================================================== #

    async def load_item(self, url: str) -> Optional[Union[MovieInfo, SeriesInfo]]:
        """Kotlin load(): dizi sayfası + her sezon sayfasından bölüm listesi."""
        target = (url or "").strip()
        if not target:
            return None

        try:
            # Bölüm/sezon linki geldiyse önce dizi sayfasına çöz (Kotlin: sonBolumler)
            if "/dizi/" not in target:
                resolved = await self._resolve_series_url(target)
                if resolved:
                    target = resolved

            html = await self._fetch_text(target)
            if not html:
                return None

            soup = BeautifulSoup(html, "html.parser")

            title_tag = soup.select_one("div.poster.poster h2") or soup.select_one("div.poster h2")
            if not title_tag:
                print(f"[!] {self.name} başlık bulunamadı: {target}")
                return None
            title = title_tag.get_text(strip=True)

            # Önce dikey poster (div.poster img), yoksa Kotlin'in kullandığı geniş banner.
            # Bazı posterler 404 döndüğü için _resolve_poster erişilebilir olanı seçer.
            portrait = soup.select_one("div.poster img")
            banner = soup.select_one("div.w-full.page-top.relative img")
            poster = await self._resolve_poster(
                (portrait.get("data-src") or portrait.get("src")) if portrait else None,
                (banner.get("data-src") or banner.get("src")) if banner else None,
            )

            description_tag = soup.select_one("div.mt-2.text-sm")
            description = description_tag.get_text(strip=True) if description_tag else None

            tags_tag = soup.select_one("div.poster.poster h3")
            tags = [t.strip() for t in tags_tag.get_text(strip=True).split(",") if t.strip()] if tags_tag else None

            rating = self._extract_rating(soup)
            year = self._extract_year(soup)
            actors = self._extract_actors(soup)
            seasons = await self._load_seasons(soup, target)

            return SeriesInfo(
                content_type="series",
                url=target,
                poster=poster,
                title=title,
                description=description,
                tags=tags,
                rating=rating,
                year=year,
                actors=actors,
                plugin=self.name,
                seasons=seasons or None,
            )
        except Exception as e:
            print(f"[!] {self.name} load_item hatası ({url}): {e}")
            return None

    async def _resolve_series_url(self, url: str) -> Optional[str]:
        """Bölüm/sezon sayfasından dizi sayfası URL'sini bulur (Kotlin: `div.poster a`)."""
        if "/dizi/" in url:
            return url

        html = await self._fetch_text(url)
        if not html:
            return None

        soup = BeautifulSoup(html, "html.parser")
        anchor = soup.select_one('a[href^="/dizi/"]') or soup.select_one("div.poster a[href]")
        if anchor and anchor.get("href"):
            return self.fix_url(anchor.get("href"))

        # Şifreli veri içinde de dizi slug'ı geçiyor (sezon sayfalarında HTML'de bağ yok)
        decoded = self._secure_text(html) or ""
        match = re.search(r'"(dizi/[A-Za-z0-9._-]+)"', decoded)
        return self.fix_url(f"/{match.group(1)}") if match else None

    @staticmethod
    def _extract_year(soup) -> Optional[str]:
        """Kotlin: `div.w-fit.min-w-fit`[1] -> `span.text-sm.opacity-60` -> son token."""
        boxes = soup.select("div.w-fit.min-w-fit")
        candidates: List[str] = []

        for box in boxes[1:3] or boxes:
            value = box.select_one("span.text-sm.opacity-60")
            if value:
                candidates.append(value.get_text(strip=True))

        for text in candidates:
            match = re.search(r"\b(19\d{2}|20\d{2})\b", text)
            if match:
                return match.group(1)
            parts = [p for p in re.split(r"\s+", text) if p]
            if parts and parts[-1].isdigit() and len(parts[-1]) == 4:
                return parts[-1]

        for text in candidates:
            parts = [p for p in re.split(r"\s+", text) if p]
            if parts and parts[-1].isdigit():
                return parts[-1]

        return None

    @staticmethod
    def _extract_rating(soup) -> Optional[str]:
        """Kotlin: `div.global-box h5` yerine IMDb kutusu varsa onu kullanır."""
        for box in soup.select("div.w-fit.min-w-fit"):
            label = box.select_one("span.text-base")
            if not label or "imdb" not in label.get_text(strip=True).lower():
                continue
            value = box.select_one("span.text-sm.opacity-60")
            if value and value.get_text(strip=True):
                return value.get_text(strip=True)
        return None

    @staticmethod
    def _extract_actors(soup) -> Optional[List[str]]:
        """Kotlin: `div.global-box h5`; yoksa 'Oyuncular' kutusundaki bağlantılar."""
        actors = [h5.get_text(strip=True) for h5 in soup.select("div.global-box h5") if h5.get_text(strip=True)]
        if actors:
            return actors

        for box in soup.select("div.w-fit.min-w-fit, div.global-box"):
            label = box.select_one("span.text-base, h3, h4")
            if not label or "oyuncu" not in label.get_text(strip=True).lower():
                continue
            names = [a.get_text(strip=True) for a in box.select("a[href]") if a.get_text(strip=True)]
            if names:
                return names

        return None

    async def _load_seasons(self, soup, referer: str) -> Dict[int, List[Episode]]:
        """Kotlin load(): sezon linkleri -> her sezon sayfasından `div.cursor-pointer` blokları."""
        links: List[str] = []
        anchors = soup.select("div.flex.items-center.flex-wrap.gap-2.mb-4 a[href]")
        if not anchors:
            anchors = [a for a in soup.select('a[href*="-sezon-"]') if re.search(r"-sezon-(?:c)?\d+", a.get("href", ""), re.IGNORECASE)]

        for anchor in anchors:
            href = anchor.get("href")
            if href and href not in links:
                links.append(href)

        grouped: Dict[int, List[str]] = {}
        for href in links:
            season_no = self._season_number(href)
            if season_no is None:
                continue
            grouped.setdefault(season_no, []).append(href)

        seasons: Dict[int, List[Episode]] = {}
        for season_no in sorted(grouped):
            for href in grouped[season_no]:
                await asyncio.sleep(self.sequential_delay)
                html = await self._fetch_text(self.fix_url(href), referer=referer)
                episodes = self._parse_episodes(html, season_no)
                if episodes:
                    seasons[season_no] = episodes
                    break

        return seasons

    def _parse_episodes(self, html: str, season_no: int) -> List[Episode]:
        """Kotlin: `div.episodes` -> `div.cursor-pointer` -> ilk `a` = no, son `a` = ad + link."""
        soup = BeautifulSoup(html or "", "html.parser")
        episodes: List[Episode] = []
        seen = set()

        # Aynı bölüm hem "Altyazılı" hem "Dublaj" sekmesinde gelir; ilk kayıt tutulur.
        for block in soup.select("div.episodes div.cursor-pointer"):
            anchors = block.select("a[href]")
            if not anchors:
                continue

            first, last = anchors[0], anchors[-1]
            episode_no = self._episode_number(first.get_text(strip=True)) or self._episode_number(last.get("href", ""))
            if episode_no is None or episode_no in seen:
                continue

            seen.add(episode_no)
            episodes.append(Episode(
                season=season_no,
                episode=episode_no,
                title=last.get_text(strip=True),
                url=self.fix_url(last.get("href")),
            ))

        return episodes

    # ================================================================== #
    # Oynatıcı bağlantıları
    # ================================================================== #

    async def load_links(self, url: str) -> List[str]:
        """Kotlin loadLinks(): secureData -> "source_content" -> iframe src."""
        target = (url or "").strip()
        if not target:
            return []

        try:
            # Dizi (ya da sezon) sayfası verilmişse ilk bölümün bağlantılarını getir
            if "/dizi/" in target or self._season_url_re.search(target):
                item = await self.load_item(target)
                if isinstance(item, SeriesInfo) and item.seasons:
                    first = next((ep for episodes in item.seasons.values() for ep in episodes), None)
                    if first and first.url and first.url != target:
                        return await self.load_links(first.url)

            html = await self._fetch_text(target)
            if not html:
                return []

            embed_urls: List[str] = []
            decoded = self._secure_text(html) or ""

            # 1) Kırık JSON'u atlayan regex: "source_content":"<iframe ...>"
            for match in re.finditer(r'"source_content"\s*:\s*"((?:[^"\\]|\\.)*)"', decoded):
                raw_html = (
                    match.group(1)
                    .replace('\\"', '"')
                    .replace("\\/", "/")
                    .replace("\\\\", "\\")
                )
                if "iframe" not in raw_html.lower():
                    continue

                iframe = BeautifulSoup(raw_html, "html.parser").select_one("iframe")
                if not iframe:
                    continue

                # src="about:blank" kontrolü YOKTU: yer tutucu embed_urls'a girebiliyordu
                # (sonda startswith("http") filtresi tutuyordu ama gerçek
                # data-src adresi de atılıyordu).
                src = EmbedHelper.en_iyi(iframe.get("src"), iframe.get("data-src"))
                if src and src not in embed_urls:
                    embed_urls.append(self.fix_url(src))

            # 2) Yedek: sayfa DOM'undaki doğrudan iframe'ler
            if not embed_urls:
                soup = BeautifulSoup(html, "html.parser")
                for iframe in soup.select("iframe[src], iframe[data-src], [data-url], [data-video]"):
                    # data-url -> data-video -> data-src -> src sırası,
                    # yer tutucu/varlık filtresi EmbedHelper'da
                    src = EmbedHelper.en_iyi(
                        iframe.get("data-url"),
                        iframe.get("data-video"),
                        iframe.get("data-src"),
                        iframe.get("src"),
                    )
                    if not src:
                        continue
                    if src not in embed_urls:
                        embed_urls.append(self.fix_url(src))

        except Exception as e:
            print(f"[!] {self.name} load_links hatası ({url}): {e}")
            return []

        # Tekrar eden (dublaj/altyazı) linkleri sırasını bozmadan temizle
        unique_urls: List[str] = []
        for link in embed_urls:
            if link and link.startswith("http") and link not in unique_urls:
                unique_urls.append(link)

        return unique_urls


if __name__ == "__main__":
    import asyncio

    async def main():
        plugin = Dizilla()
        try:
            print("--- search ---")
            for item in await plugin.search("breaking bad"):
                print(item.title, "|", item.year, "|", item.url)

            print("--- ana sayfa (Yeni Eklenen Bölümler) ---")
            for item in await plugin.get_main_page(1, plugin.main_page["Yeni Eklenen Bölümler"], "Yeni Eklenen Bölümler"):
                print(item.title, "|", item.url)

            print("--- ana sayfa (Aksiyon, sayfa 2) ---")
            for item in (await plugin.get_main_page(2, plugin.main_page["Aksiyon"], "Aksiyon"))[:5]:
                print(item.title, "|", item.url)

            print("--- detay ---")
            detail = await plugin.load_item(f"{plugin.main_url}/dizi/breaking-bad-2")
            print(detail.model_dump_json(indent=2)[:1500] if detail else "detay yok")

            print("--- linkler ---")
            print(await plugin.load_links(f"{plugin.main_url}/breaking-bad-1-sezon-1-bolum-c02"))
        finally:
            await plugin.close()

    asyncio.run(main())
