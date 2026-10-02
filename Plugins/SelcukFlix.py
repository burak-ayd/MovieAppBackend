# Oluşturan: Burak Aydoğan

import asyncio
import base64
import json
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from bs4 import BeautifulSoup
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from Core.Helpers.EmbedHelper import EmbedHelper
from Core.Plugin.PluginBase import PluginBase
from Core.Plugin.PluginModels import Episode, MainPageResult, MovieInfo, SearchResult, SeriesInfo


# Kategori sıralaması: API'nin `orderType` parametresi.
# (Geçersiz bir değer gönderilirse site sessizce `date_desc` davranışına düşüyor.)
GECERLI_SIRALAMALAR = ("date_desc", "date_asc", "imdb_desc", "imdb_asc", "title_asc")

# (kategori_id, görünen ad) — kaynak: findMovies / findSeries uçları
FILM_KATEGORILERI = (
    ("49", "Aile Film"), ("44", "Animasyon Film"), ("59", "Aksiyon Film"),
    ("66", "Bilim Kurgu Film"), ("48", "Dram Film"), ("61", "Fantastik Film"),
    ("68", "Gerilim Film"), ("51", "Gizem Film"), ("63", "Korku Film"),
    ("45", "Komedi Film"), ("65", "Romantik Film"), ("46", "Suç Film"),
    ("69", "Savaş Film"), ("78", "Western Film"),
)

DIZI_KATEGORILERI = (
    ("15", "Aile Dizi"), ("17", "Animasyon Dizi"), ("9", "Aksiyon Dizi"),
    ("5", "Bilim Kurgu Dizi"), ("2", "Dram Dizi"), ("12", "Fantastik Dizi"),
    ("18", "Gerilim Dizi"), ("3", "Gizem Dizi"), ("8", "Korku Dizi"),
    ("4", "Komedi Dizi"), ("7", "Romantik Dizi"), ("1", "Suç Dizi"),
    ("26", "Savaş Dizi"), ("11", "Western Dizi"),
)


def kategori_sorgusu(cid: str, order: str = "date_desc", page: int = 1) -> str:
    """findMovies / findSeries sorgu dizesi."""
    return (
        "releaseYearStart=1900&releaseYearEnd=2024&imdbPointMin=5&imdbPointMax=10"
        f"&categoryIdsComma={cid}&countryIdsComma=&orderType={order}&languageId=-1"
        f"&currentPage={page}&currentPageCount=24&queryStr=&categorySlugsComma=&countryCodesComma="
    )


def kategorileri_olustur(main_url: str, order: str = "date_desc") -> Dict[str, str]:
    """Ana sayfa sözlüğü. İlk sıra her zaman "Ana Sayfa" (kök adres).

    Sıralama değiştirildiğinde sözlük bu fonksiyondan yeniden kurulur.
    """
    kok = main_url.rstrip("/")
    sayfalar: Dict[str, str] = {
        "Ana Sayfa": kok,
        "Yeni Eklenen Filmler": f"{kok}/film-izle",
        "Yeni Eklenen Diziler": f"{kok}/dizi-izle",
    }
    for cid, ad in FILM_KATEGORILERI:
        sayfalar[ad] = f"{kok}/api/bg/findMovies?{kategori_sorgusu(cid, order)}"
    for cid, ad in DIZI_KATEGORILERI:
        sayfalar[ad] = f"{kok}/api/bg/findSeries?{kategori_sorgusu(cid, order)}"
    return sayfalar


class SelcukFlix(PluginBase):
    """SelcukFlix kaynak site kazıyıcısı (film + dizi, AES-CBC şifreli sayfa verisi).

    Kotlin (cloudstream3) karşılıkları:
        * ``mainPage`` / ``getMainPage`` -> ``main_page`` / ``get_main_page``
        * ``search``                      -> ``search``   (API + HTML yedeği)
        * ``load``                        -> ``load_item`` (MovieInfo / SeriesInfo)
        * ``loadLinks``                   -> ``load_links``
        * ``extractSecureData`` + ``decryptAES`` -> ``_secure_payload``
        * ``fixPosterUrl``                -> ``fix_poster_url``

    Notlar:
        * Site Next.js tabanlıdır; veriler ``script#__NEXT_DATA__`` içindeki
          ``props.pageProps.secureData`` alanında gelir.
        * ``secureData`` ``eyJ`` ile başlıyorsa düz base64 JSON, değilse AES-CBC çözülür
          (Kotlin'deki ``decodeSecureData`` mantığı).
        * Bölüm ve film kaynakları ``RelatedResults`` içinden gelir; iframe host'ları
          gerekirse ``sn.hotlinger.com``'a yönlendirilir (Kotlin'deki replace).
    """

    name = "SelcukFlix"
    language = "tr"
    main_url = "https://selcukflix.com"
    description = "SelcukFlix - Film ve dizi izleme platformu"
    favicon = f"https://www.google.com/s2/favicons?domain={main_url}&sz=256"

    # Kotlin: PRIVATE_AES_KEY / IvParameterSpec(ByteArray(16)) / AES-CBC-PKCS5Padding
    # (Dizilla ile aynı anahtar)
    _private_aes_key = b"9bYMCNQiWsXIYFWYAu7EkdsSbmGBTyUI"
    _aes_iv = bytes(16)

    # Kotlin: sequentialMainPageDelay = 50L
    sequential_delay = 0.05
    request_timeout = 30

    # Poster doğrulama önbelleği (aynı CDN adresi tekrar tekrar sorgulanmasın)
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

    # Kategori sıralaması (API'nin orderType parametresi).
    # Değerler: date_desc (varsayılan) · date_asc · imdb_desc · imdb_asc · title_asc
    # Çalışma anında değiştirmek için: eklenti.set_order_type("imdb_desc")
    order_type = "date_desc"

    # İlk iki kategori HTML sayfasıdır (film-izle / dizi-izle), gerisi şifreli API.
    main_page = kategorileri_olustur(main_url, order_type)


    # ================================================================== #
    # Yardımcılar
    # ================================================================== #

    def set_order_type(self, order: str) -> bool:
        """Kategori sıralamasını çalışma anında değiştirir.

        >>> plugin.set_order_type("imdb_desc")   # en yüksek puanlılar önce
        >>> plugin.set_order_type("date_desc")   # en yeniler önce (varsayılan)

        main_page sözlüğü geçerli `self.main_url` ile yeniden kurulur; bu sayede
        `url_update` sonrasında da doğru adresler üretilir.
        """
        if order not in GECERLI_SIRALAMALAR:
            print(f"[!] {self.name} geçersiz sıralama: '{order}' | seçenekler: {', '.join(GECERLI_SIRALAMALAR)}")
            return False

        self.order_type = order
        self.main_page = kategorileri_olustur(self.main_url, order)
        print(f"[{self.name}] kategori sıralaması -> {order}")
        return True

    def _decrypt(self, encrypted_b64: str) -> Optional[str]:
        """Kotlin decryptAES: AES/CBC/PKCS5Padding, sıfır IV."""
        if not encrypted_b64:
            return None
        try:
            raw = base64.b64decode(encrypted_b64)
            cipher = Cipher(algorithms.AES(self._private_aes_key), modes.CBC(self._aes_iv))
            decryptor = cipher.decryptor()
            padded = decryptor.update(raw) + decryptor.finalize()
            unpadder = padding.PKCS7(128).unpadder()
            return (unpadder.update(padded) + unpadder.finalize()).decode("utf-8")
        except Exception as e:
            print(f"[!] {self.name} çözme hatası: {e}")
            return None

    def _decode_secure_data(self, secure_data: str) -> Optional[str]:
        """Kotlin decodeSecureData: 'eyJ...' ise düz base64, değilse AES."""
        if not secure_data:
            return None
        if secure_data.startswith("eyJ"):
            try:
                return base64.b64decode(secure_data).decode("utf-8")
            except Exception:
                return None
        return self._decrypt(secure_data)

    def _secure_payload(self, html: str) -> Dict[str, Any]:
        """__NEXT_DATA__ -> props.pageProps.secureData -> çözülmüş JSON sözlüğü."""
        node = BeautifulSoup(html or "", "html.parser").select_one("script#__NEXT_DATA__")
        if not node or not node.string:
            return {}

        try:
            secure_data = json.loads(node.string)["props"]["pageProps"].get("secureData")
        except Exception:
            return {}

        text = self._decode_secure_data(secure_data or "")
        if not text:
            return {}

        try:
            data = json.loads(text)
        except Exception:
            return {}

        return data if isinstance(data, dict) else {}

    def fix_poster_url(self, url: Optional[str]) -> Optional[str]:
        """Kotlin fixPosterUrl: AMP öneki atılır, CDN host'ları normalize edilir,
        ``/f/f/`` yüksek çözünürlüklü ``/630/910/`` boyutuna çevrilir."""
        if not url or url == "null":
            return None

        cleaned = url.replace("images-macellan-online.cdn.ampproject.org/i/s/", "")
        cleaned = re.sub(r"file\.[\w.]+/", "file.macellan.online/", cleaned)
        cleaned = re.sub(r"images\.[\w.]+/", "images.macellan.online/", cleaned)
        cleaned = cleaned.replace("/f/f/", "/630/910/")

        return self.fix_url(cleaned)

    async def _image_ok(self, url: str) -> bool:
        """Poster adresinin gerçekten görsel döndürdüğünü HEAD ile doğrular (önbellekli)."""
        if not url:
            return False

        cached = self._poster_cache.get(url)
        if cached is not None:
            return cached

        ok = False
        try:
            resp = await self.client.head(url, headers=self._page_headers(), timeout=10, follow_redirects=True)
            ok = resp.status_code == 200 and resp.headers.get("content-type", "").startswith("image/")
        except Exception:
            ok = False

        if len(self._poster_cache) > 5000:
            self._poster_cache.clear()
        self._poster_cache[url] = ok

        return ok

    async def _resolve_poster(self, *raw_urls: Optional[str]) -> Optional[str]:
        """Verilen alanları sırayla dener, ilk erişilebilir posteri döner.

        Hiçbiri doğrulanamazsa ilk adayın dönüştürülmüş hâlini döner (davranış bozulmaz).
        """
        yedek: Optional[str] = None

        for raw in raw_urls:
            if not raw:
                continue

            candidate = self.fix_poster_url(raw)
            if not candidate:
                continue
            yedek = yedek or candidate

            if await self._image_ok(candidate):
                return candidate

            # Dönüşüm işe yaramadıysa ham adresi dene
            ham = self.fix_url(raw)
            if ham and await self._image_ok(ham):
                return ham

        return yedek

    async def _resolve_posters(self, items: List[Dict[str, Any]], *fields: str) -> List[Optional[str]]:
        """Sayfa içindeki tüm posterleri paralel doğrular (aksi halde 24 kart = 24 sıralı istek)."""
        return list(await asyncio.gather(*(
            self._resolve_poster(*(item.get(field) for field in fields)) for item in items
        )))

    def _page_headers(self, referer: Optional[str] = None, api: bool = False) -> Dict[str, str]:
        headers = dict(self.api_headers if api else self.headers)
        headers["Referer"] = referer or f"{self.main_url}/"
        return headers

    @staticmethod
    def _is_cf_challenge(text: str) -> bool:
        head = (text or "")[:20000].lower()
        return any(marker in head for marker in (
            "just a moment",
            "cf-browser-verification",
            "challenge-platform",
            "cf_chl_opt",
            "checking your browser",
            "verifying",
        ))

    async def _fetch_text(self, url: str, referer: Optional[str] = None) -> str:
        """Sayfayı çeker; Cloudflare koruması varsa Playwright'a düşer."""
        text = ""
        try:
            resp = await self.client.get(url, headers=self._page_headers(referer), timeout=self.request_timeout,
                                        follow_redirects=True)
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

    @staticmethod
    def _clean_title(raw: Optional[str]) -> str:
        """img alt metninden '1. Sezon 4. Bölüm' / 'izle' gibi ekleri temizler."""
        if not raw:
            return ""
        temiz = re.sub(r"\d+\.\s*(Sezon|Bölüm)", " ", raw, flags=re.IGNORECASE)
        temiz = re.sub(r"\b(izle|full film|filmi full)\b", " ", temiz, flags=re.IGNORECASE)
        return " ".join(temiz.split())

    @staticmethod
    def _series_url(href: str) -> str:
        """Bölüm linkinden dizi sayfası URL'si: /dizi/slug/sezon-1/bolum-1 -> /dizi/slug"""
        return href.split("/sezon")[0]

    # ================================================================== #
    # Ana sayfa
    # ================================================================== #

    async def get_main_page(self, page: int = 1, url: str = "", category: str = "") -> List[MainPageResult]:
        """Kategori listesi: findMovies / findSeries API dalları, yoksa HTML kartları."""
        data = (url or "").strip() or self.main_url
        page = max(1, int(page or 1))

        try:
            if "api/bg/findMovies" in data:
                return await self._api_kategori_sayfasi(page, data, category, dizi_mi=False)
            if "api/bg/findSeries" in data:
                return await self._api_kategori_sayfasi(page, data, category, dizi_mi=True)
            return await self._html_kategori_sayfasi(page, data, category)
        except Exception as e:
            print(f"[!] {self.name} get_main_page hatası: {e}")
            return []

    async def _api_cevap(self, url: str, page: int) -> Dict[str, Any]:
        """POST /api/bg/find* -> şifreli `response` alanının çözülmüş JSON'u.

        Bu uçlar `success` anahtarı döndürmüyor (searchContent'den farklı), bu yüzden
        yalnızca `response` alanına bakılıyor.
        """
        target = re.sub(r"currentPage=\d+", f"currentPage={page}", url)

        headers = self._page_headers(api=True)
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        headers["Origin"] = self.main_url

        resp = await self.client.post(target, headers=headers, data={"page": str(page)},
                                      timeout=self.request_timeout, follow_redirects=True)
        if resp.status_code != 200:
            print(f"[!] {self.name} kategori API {resp.status_code}: {target[:110]}")
            return {}

        try:
            payload = resp.json()
        except Exception as e:
            print(f"[!] {self.name} kategori API JSON hatası: {e}")
            return {}

        blob = payload.get("response") if isinstance(payload, dict) else None
        text = self._decode_secure_data(blob) if blob else None
        if not text:
            return {}

        try:
            data = json.loads(text)
        except Exception:
            data = self._result_dizisi(text)

        return data if isinstance(data, dict) else {}

    @staticmethod
    def _result_dizisi(text: str) -> Dict[str, Any]:
        """JSON bütün çözülemiyorsa `"result":[ ... ]` dizisini parantez sayacıyla ayıklar."""
        match = re.search(r'"result"\s*:\s*\[', text)
        if not match:
            return {}

        start = match.end() - 1
        depth = 0
        in_string = False
        escaped = False
        for i in range(start, len(text)):
            char = text[i]
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
                        return {"result": json.loads(text[start:i + 1])}
                    except Exception:
                        return {}
        return {}

    async def _api_kategori_sayfasi(self, page: int, url: str, category: str, dizi_mi: bool) -> List[MainPageResult]:
        """Kategori ID'li film/dizi listesi (şifreli API yanıtı)."""
        data = await self._api_cevap(url, page)
        items = data.get("result") or []
        if not items:
            return []

        posters = await self._resolve_posters(
            items, "poster_url", "square_url", "face_url", "back_url"
        )

        results: List[MainPageResult] = []
        for item, poster in zip(items, posters):
            slug = str(item.get("used_slug") or "").strip("/")
            title = item.get("original_title") or item.get("culture_title")
            if not slug or not title:
                continue

            year = item.get("release_year")
            results.append(MainPageResult(
                title=str(title).strip(),
                url=self.fix_url(f"/{slug}"),
                category=category or ("Yeni Eklenen Diziler" if dizi_mi else "Yeni Eklenen Filmler"),
                poster=poster,
                release_date=str(year) if year else None,
                rating=str(item.get("imdb_point")) if item.get("imdb_point") else None,
                plugin=self.name,
            ))

        return results

    async def _html_kategori_sayfasi(self, page: int, data: str, category: str) -> List[MainPageResult]:
        """HTML kartları (film-izle / dizi-izle)."""
        target = self.fix_url(data)
        if page > 1 and "?" not in target:
            target = f"{target}?page={page}"

        try:
            html = await self._fetch_text(target)
            soup = BeautifulSoup(html or "", "html.parser")

            kok = self.main_url.rstrip("/")
            if data.rstrip("/") == kok:
                # Ana sayfa: film ve dizi kartlarının ikisi de yer alır
                seciciler = ['a[href*="/film/"]', 'a[href*="/seri-filmler/"]', 'a[href*="/dizi/"]']
            elif "/dizi" in data:
                seciciler = ['a[href*="/dizi/"]']
            else:
                seciciler = ['a[href*="/film/"]', 'a[href*="/seri-filmler/"]']

            kartlar: List[Dict[str, Any]] = []
            for secici in seciciler:
                for el in soup.select(secici):
                    href = el.get("href")
                    if not href:
                        continue
                    link = self.fix_url(href)
                    if link in (f"{self.main_url}/film-izle", f"{self.main_url}/dizi-izle",
                                f"{self.main_url}/seri-filmler"):
                        continue

                    image = el.select_one("img")
                    baslik_el = el.select_one("h2,h3")
                    baslik = (
                        baslik_el.get_text(strip=True) if baslik_el
                        else self._clean_title(image.get("alt") if image else None)
                    )
                    if not baslik:
                        continue

                    poster = None
                    if image:
                        poster = image.get("data-src") or image.get("src")

                    kartlar.append({
                        "baslik": baslik,
                        "url": link,
                        "poster": poster,
                        "dizi": "/dizi/" in link,
                    })

            # Sayfa kartları tek seferde geldiği için doğrulamayı paralel yap
            posterler = await asyncio.gather(*(self._resolve_poster(k["poster"]) for k in kartlar))

            results: List[MainPageResult] = []
            for kart, poster in zip(kartlar, posterler):
                if kart["dizi"]:
                    results.append(MainPageResult(
                        title=kart["baslik"],
                        url=self._series_url(kart["url"]),
                        category=category or "Yeni Eklenen Diziler",
                        poster=poster,
                        plugin=self.name,
                    ))
                else:
                    results.append(MainPageResult(
                        title=kart["baslik"],
                        url=kart["url"],
                        category=category or "Yeni Eklenen Filmler",
                        poster=poster,
                        plugin=self.name,
                    ))

            # Aynı kartları tekrarlama (sayfa içinde birden fazla a etiketi olabiliyor)
            unique: List[MainPageResult] = []
            seen = set()
            for item in results:
                if item.url in seen:
                    continue
                seen.add(item.url)
                unique.append(item)
            return unique

        except Exception as e:
            print(f"[!] {self.name} HTML kategori hatası: {e}")
            return []

    # ================================================================== #
    # Arama
    # ================================================================== #

    async def search(self, query: str) -> List[SearchResult]:
        """Kotlin search(): şifreli arama API'si, sonuç yoksa /arama sayfası."""
        results: List[SearchResult] = []
        try:
            resp = await self.client.post(
                f"{self.main_url}/api/bg/searchcontent?searchterm={query}",
                headers=self._page_headers(api=True),
                timeout=self.request_timeout,
            )
            payload = resp.json()
        except Exception as e:
            print(f"[!] {self.name} arama API hatası: {e}")
            payload = {}

        blob = payload.get("response") if isinstance(payload, dict) else None
        decoded = self._decrypt(blob) if blob else None

        if decoded:
            try:
                data = json.loads(decoded)
            except Exception:
                data = {}

            for item in data.get("result") or []:
                slug = str(item.get("used_slug") or "")
                if "/seri-filmler/" in slug:
                    continue

                title = item.get("object_name")
                if not title or not slug:
                    continue

                link = self.fix_url(slug)
                poster = await self._resolve_poster(item.get("object_poster_url"))

                if "/film/" in link:
                    results.append(SearchResult(
                        title=str(title).strip(),
                        url=link,
                        poster=poster,
                        year=item.get("object_release_year") or item.get("release_year"),
                        rating=str(item.get("imdb_point")) if item.get("imdb_point") else None,
                        media_type="Film",
                        plugin=self.name,
                    ))
                elif "/dizi/" in link:
                    results.append(SearchResult(
                        title=str(title).strip(),
                        url=self._series_url(link),
                        poster=poster,
                        year=item.get("object_release_year") or item.get("release_year"),
                        rating=str(item.get("imdb_point")) if item.get("imdb_point") else None,
                        media_type="Dizi",
                        plugin=self.name,
                    ))

        # API boş dönerse HTML arama sayfasına düş
        if not results:
            results = await self._search_html(query)

        unique: List[SearchResult] = []
        seen = set()
        for item in results:
            if item.url in seen:
                continue
            seen.add(item.url)
            unique.append(item)
        return unique

    async def _search_html(self, query: str) -> List[SearchResult]:
        """Kotlin'deki /arama?q= yedeği."""
        results: List[SearchResult] = []
        try:
            html = await self._fetch_text(f"{self.main_url}/arama?q={query}")
            soup = BeautifulSoup(html or "", "html.parser")

            for el in soup.select('a[href^="/film/"], a[href^="/dizi/"]'):
                href = el.get("href")
                if not href:
                    continue
                link = self.fix_url(href)
                if link in (f"{self.main_url}/film-izle", f"{self.main_url}/dizi-izle"):
                    continue

                image = el.select_one("img")
                baslik_el = el.select_one("h2,h3")
                baslik = (baslik_el.get_text(strip=True) if baslik_el
                          else self._clean_title(image.get("alt") if image else None))
                if not baslik:
                    continue

                poster = None
                if image:
                    poster = image.get("data-src") or image.get("src")

                dizi_mi = "/dizi/" in link
                results.append(SearchResult(
                    title=baslik,
                    url=self._series_url(link) if dizi_mi else link,
                    poster=await self._resolve_poster(poster),
                    media_type="Dizi" if dizi_mi else "Film",
                    plugin=self.name,
                ))
        except Exception as e:
            print(f"[!] {self.name} HTML arama hatası: {e}")

        return results

    # ================================================================== #
    # İçerik detayı
    # ================================================================== #

    async def load_item(self, url: str) -> Optional[Union[MovieInfo, SeriesInfo]]:
        """Kotlin load(): film -> MovieInfo, dizi -> SeriesInfo (sezon/bölüm listesiyle)."""
        target = (url or "").strip()
        if not target:
            return None

        try:
            html = await self._fetch_text(target)
            if not html:
                return None

            soup = BeautifulSoup(html, "html.parser")
            h1 = soup.select_one("h1")
            sayfa_basligi = h1.get_text(strip=True) if h1 else ""
            is_series = "/dizi/" in target

            payload = self._secure_payload(html)
            item = payload.get("contentItem") or {}

            title = (item.get("original_title") or "").strip() or sayfa_basligi
            if not title:
                print(f"[!] {self.name} başlık bulunamadı: {target}")
                return None

            description = self._temiz_aciklama(item.get("description"))
            poster = await self._resolve_poster(item.get("poster_url"))
            year = item.get("release_year")
            year = str(year) if year and int(year) > 0 else None
            rating = str(item.get("imdb_point")) if item.get("imdb_point") else None
            tags = self._kategoriler(item.get("categories"))

            if is_series:
                seasons = await self._sezonlari(payload, soup, target)
                return SeriesInfo(
                    content_type="series",
                    url=target,
                    poster=poster,
                    title=title,
                    description=description,
                    tags=tags,
                    rating=rating,
                    year=year,
                    actors=self._oyuncular(payload),
                    plugin=self.name,
                    seasons=seasons or None,
                )

            return MovieInfo(
                url=target,
                title=title,
                description=description,
                poster_url=poster,
                genre=tags or [],
                imdb_id=None,
                release_date=year,
                rating=rating,
                runtime_minutes=int(item.get("total_minutes") or 0),
                cast_members=self._oyuncular(payload) or [],
                plugin=self.name,
            )

        except Exception as e:
            print(f"[!] {self.name} load_item hatası ({url}): {e}")
            return None

    @staticmethod
    def _temiz_aciklama(raw: Optional[str]) -> Optional[str]:
        """Kotlin'deki \\n, \\r ve ters eğik çizgi temizliği."""
        if not raw or raw == "null":
            return None
        return raw.replace("\\n", "\n").replace("\\r", "").replace("\\", "").strip() or None

    @staticmethod
    def _kategoriler(raw: Optional[str]) -> List[str]:
        if not raw or raw == "null":
            return []
        return [t.strip() for t in str(raw).split(",") if t.strip()]

    @staticmethod
    def _oyuncular(payload: Dict[str, Any]) -> Optional[List[str]]:
        """getMovieCastsById / getSerieCastsById -> actor_name"""
        related = payload.get("RelatedResults") or {}
        for anahtar in ("getMovieCastsById", "getSerieCastsById"):
            node = related.get(anahtar) or {}
            oyuncular = [c.get("actor_name") for c in (node.get("result") or []) if c.get("actor_name")]
            if oyuncular:
                return oyuncular
        return None

    async def _sezonlari(self, payload: Dict[str, Any], soup, referer: str) -> Dict[int, List[Episode]]:
        """RelatedResults.getSerieSeasonAndEpisodes -> {sezon: [Episode]}"""
        related = payload.get("RelatedResults") or {}
        sezonlar: Dict[int, List[Episode]] = {}

        for sezon in (related.get("getSerieSeasonAndEpisodes") or {}).get("result") or []:
            if not isinstance(sezon, dict):
                continue
            sezon_no = sezon.get("season_no")
            if sezon_no is None:
                continue
            try:
                sezon_no = int(sezon_no)
            except (TypeError, ValueError):
                continue

            bolumler: List[Episode] = []
            for bolum in sezon.get("episodes") or []:
                if not isinstance(bolum, dict):
                    continue
                slug = bolum.get("used_slug")
                bolum_no = bolum.get("episode_no")
                if not slug or bolum_no is None:
                    continue
                try:
                    bolum_no = int(bolum_no)
                except (TypeError, ValueError):
                    continue

                bolumler.append(Episode(
                    season=sezon_no,
                    episode=bolum_no,
                    title=bolum.get("episode_text") or f"{sezon_no}. Sezon {bolum_no}. Bölüm",
                    url=self.fix_url(slug),
                ))

            if bolumler:
                sezonlar.setdefault(sezon_no, []).extend(bolumler)

        if sezonlar:
            return sezonlar

        # Yedek: sayfadaki /sezon-N/.../bolum-M linkleri
        for link in soup.select('a[href*="/sezon-"]'):
            href = link.get("href") or ""
            s_match = re.search(r"/sezon-(\d+)", href)
            e_match = re.search(r"/bolum-(\d+)", href)
            if not s_match or not e_match:
                continue
            sezon_no, bolum_no = int(s_match.group(1)), int(e_match.group(1))
            sezonlar.setdefault(sezon_no, []).append(Episode(
                season=sezon_no,
                episode=bolum_no,
                title=link.get_text(strip=True) or f"{sezon_no}. Sezon {bolum_no}. Bölüm",
                url=self.fix_url(href),
            ))

        return sezonlar

    # ================================================================== #
    # Oynatıcı bağlantıları
    # ================================================================== #

    async def load_links(self, url: str) -> List[str]:
        """Kotlin loadLinks(): RelatedResults -> source_content -> iframe src."""
        target = (url or "").strip()
        if not target:
            return []

        try:
            html = await self._fetch_text(target)
            if not html:
                return []

            payload = self._secure_payload(html)
            related = payload.get("RelatedResults") or {}
            if not related:
                konsol_hata = f"{self.name} şifreli veri çözülemedi: {target}"
                print(f"[!] {konsol_hata}")
                return []

            kaynaklar = self._kaynak_icerikleri(related, target)
            if not kaynaklar:
                print(f"[!] {self.name} kaynak bulunamadı: {target}")
                return []

            embed_urls: List[str] = []
            for icerik in kaynaklar:
                iframe = BeautifulSoup(icerik or "", "html.parser").select_one("iframe")
                if not iframe:
                    continue
                # Lazy-load: önce src deniyordu; src="about:blank" olduğunda
                # data-src'ye hiç bakılmadan iframe atılıyordu. Sıra ve
                # temizleme artık EmbedHelper'da tek yerde.
                src = EmbedHelper.en_iyi(iframe.get("src"), iframe.get("data-src"))
                if not src:
                    continue

                link = self.fix_url(src)
                # Kotlin: dplayer host'ları hotlinger'a yönlendirilir
                link = (link.replace("sn.dplayer74.site", "sn.hotlinger.com")
                            .replace("sn.dplayer82.site", "sn.hotlinger.com")
                            .replace("sn.dplayer.site", "sn.hotlinger.com"))

                if link not in embed_urls:
                    embed_urls.append(link)

            return embed_urls

        except Exception as e:
            print(f"[!] {self.name} load_links hatası ({url}): {e}")
            return []

    def _kaynak_icerikleri(self, related: Dict[str, Any], url: str) -> List[str]:
        """Dizi/bölüm: getEpisodeSources · Film: tüm getMoviePartSourcesById_<id> kayıtları.

        Kotlin yalnızca ilk parçayı deniyordu; burada kaynağı olan tüm parçalar toplanıyor
        (dublaj + altyazı birlikte listelenebiliyor).
        """
        icerikler: List[str] = []

        if "/dizi/" in url or "/bolum-" in url or "/sezon-" in url:
            for kayit in (related.get("getEpisodeSources") or {}).get("result") or []:
                if isinstance(kayit, dict) and kayit.get("source_content"):
                    icerikler.append(kayit["source_content"])
            return icerikler

        # Film: önce ilk parça (Kotlin mantığı), sonra kaynağı olan diğer parçalar
        parcalar = (related.get("getMoviePartsById") or {}).get("result") or []
        sira: List[str] = []
        for parca in parcalar:
            if isinstance(parca, dict) and parca.get("id") is not None:
                sira.append(f"getMoviePartSourcesById_{parca['id']}")
        sira += [k for k in related if k.startswith("getMoviePartSourcesById_") and k not in sira]

        for anahtar in sira:
            for kayit in (related.get(anahtar) or {}).get("result") or []:
                if isinstance(kayit, dict) and kayit.get("source_content"):
                    icerikler.append(kayit["source_content"])

        if not icerikler:
            for kayit in (related.get("getMovieSourcesById") or {}).get("result") or []:
                if isinstance(kayit, dict) and kayit.get("source_content"):
                    icerikler.append(kayit["source_content"])

        return icerikler


if __name__ == "__main__":
    import asyncio

    async def main():
        plugin = SelcukFlix()
        try:
            print("--- filmler ---")
            for item in (await plugin.get_main_page(1, plugin.main_page["Yeni Eklenen Filmler"],
                                                    "Yeni Eklenen Filmler"))[:5]:
                print(item.title, "|", item.url, "|", (item.poster or "")[:70])

            print("--- diziler ---")
            for item in (await plugin.get_main_page(1, plugin.main_page["Yeni Eklenen Diziler"],
                                                    "Yeni Eklenen Diziler"))[:5]:
                print(item.title, "|", item.url, "|", (item.poster or "")[:70])

            print("--- arama ---")
            for item in await plugin.search("matrix"):
                print(item.title, "|", item.url, "|", item.media_type)

            print("--- film detayı ---")
            film = await plugin.load_item(f"{plugin.main_url}/film/the-animatrix/izle")
            print(film.model_dump_json(indent=1)[:600] if film else "yok")

            print("--- dizi detayı ---")
            dizi = await plugin.load_item(f"{plugin.main_url}/dizi/sinatra-all-or-nothing-at-all")
            print("sezonlar:", {s: len(e) for s, e in (dizi.seasons or {}).items()} if dizi else "yok")

            print("--- linkler ---")
            print(await plugin.load_links(f"{plugin.main_url}/dizi/sinatra-all-or-nothing-at-all/sezon-1/bolum-1"))
            print(await plugin.load_links(f"{plugin.main_url}/film/livestream-from-hell/izle"))
        finally:
            await plugin.close()

    asyncio.run(main())
