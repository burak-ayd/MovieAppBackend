# Bu araç @keyiflerolsun tarafından | @KekikAkademi için yazılmıştır.
# Python portu: Kekik-cloudstream / ContentXExtractor.kt (ve ondan türeyen alt sınıflar)

import json
import re
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

from Core.Extractor.ExtractorModels import ExtractResult, Subtitle
from Core.Helpers import debug_log


class ContentXPlayer:
    """ContentX oynatıcı ailesinin ortak çözüm mantığı.

    Kotlin tarafında ``ContentXExtractor.kt`` tek bir sınıftır; ``Hotlinger``,
    ``FourCX``, ``PlayRu``, ``FourPlayRu``, ``Pichive``, ``FourPichive`` ve
    ``SNplayer`` sadece ``name``/``mainUrl`` değiştirerek ondan türetilmiştir
    (``class Hotlinger : ContentX()``). Bu yüzden Python'da da tek bir uygulama
    yazılıp her host için ince bir sınıfla (bkz. ``Extractors/ContentX.py``,
    ``Hotlinger.py``, ``Pichive.py``) kullanılır.

    Akış:
        1. ``iframe.php`` sayfasından ``window.openPlayer('<playList>', '<reqHash>', ..., <altyazılar>)``
        2. Aynı host'ta ``source2.php?v=<playList>`` -> ``{"playlist":[{"sources":[{...,"file": "https://host/m.php?v=..."}]}]}``
        3. ``m.php`` -> ``master.m3u8`` (Kotlin'deki replace) ve ham ``file`` aday olarak denenir
        4. Doğru (url, referer) ikilisi canlı doğrulanır; bu kritik çünkü oynatma istekleri
           Referer kontrolü yapıyor ve yanlış referer 404 döndürüyor.
        5. (varsa) sayfadaki ``,'<token>',"Türkçe"`` dublaj alternatifi ikinci kaynak olarak eklenir.
    """

    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    )

    # Cloudflare'in "Attention Required" / "Just a moment" sayfaları
    _cf_markers = (
        "just a moment",
        "attention required",
        "cf-browser-verification",
        "challenge-platform",
        "cf_chl_opt",
        "checking your browser",
    )

    # ------------------------------------------------------------------ #
    # Sayfa / yanıt çekme
    # ------------------------------------------------------------------ #

    def _is_blocked(self, text: str) -> bool:
        head = (text or "")[:20000].lower()
        return any(marker in head for marker in self._cf_markers)

    async def _fetch_text(self, url: str, referer: str) -> str:
        """Embed sayfasını çeker: httpx -> cloudscraper -> curl_cffi."""
        import asyncio

        headers = {
            "User-Agent": self.user_agent,
            "Referer": referer,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        origin = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
        headers["Origin"] = origin

        text = ""
        try:
            resp = await self.client.get(url, headers=headers, follow_redirects=True)
            text = resp.text or ""
            if "openPlayer" in text:
                return text
        except Exception as e:
            debug_log(f"[{type(self).__name__}] httpx hatası: {e!r}")

        if "openPlayer" in text:
            return text

        loop = asyncio.get_event_loop()
        try:
            cs_text = await loop.run_in_executor(
                None, lambda: self.cloudscraper.get(url, headers=headers, timeout=20).text
            )
            if "openPlayer" in (cs_text or ""):
                return cs_text
        except Exception as e:
            debug_log(f"[{type(self).__name__}] cloudscraper hatası: {e!r}")

        try:
            from curl_cffi.requests import AsyncSession

            async def _cffi() -> str:
                async with AsyncSession(impersonate="chrome120") as session:
                    r = await session.get(url, headers=headers, timeout=20)
                    return r.text or ""

            if "openPlayer" in await _cffi():
                return await _cffi()
        except Exception as e:
            debug_log(f"[{type(self).__name__}] curl_cffi hatası: {e!r}")

        return text

    async def _fetch_json(self, url: str, referer: str) -> Optional[Dict[str, Any]]:
        resp = await self.client.get(url, headers={
            "User-Agent": self.user_agent,
            "Referer": referer,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
        }, follow_redirects=True)

        if resp.status_code != 200:
            debug_log(f"[{type(self).__name__}] {resp.status_code} » {url[:100]}")
            return None

        try:
            return resp.json()
        except Exception as e:
            debug_log(f"[{type(self).__name__}] JSON hatası: {e!r}")
            return None

    # ------------------------------------------------------------------ #
    # openPlayer ayrıştırma
    # ------------------------------------------------------------------ #

    @staticmethod
    def _split_js_args(raw: str) -> List[str]:
        """JS fonksiyon çağrısının argümanlarını tırnak/kaçış/parantez duyarlı ayırır."""
        args: List[str] = []
        current = ""
        quote: Optional[str] = None
        escaped = False
        depth = 0

        for char in raw:
            if escaped:
                current += char
                escaped = False
                continue
            if char == "\\":
                current += char
                escaped = True
                continue
            if quote:
                current += char
                if char == quote:
                    quote = None
                continue
            if char in "'\"":
                quote = char
                current += char
                continue
            if char in "([{":
                depth += 1
                current += char
                continue
            if char in ")]}":
                depth -= 1
                current += char
                continue
            if char == "," and depth == 0:
                args.append(current.strip())
                current = ""
                continue
            current += char

        if current.strip():
            args.append(current.strip())

        return args

    def _parse_open_player(self, html: str) -> Tuple[str, List[Subtitle]]:
        """``window.openPlayer(...)`` çağrısından playList token'ını ve altyazıları çıkarır."""
        match = re.search(r"window\.openPlayer\s*\((.*?)\)\s*;", html, re.DOTALL)
        if not match:
            return "", []

        args = self._split_js_args(match.group(1))
        if not args:
            return "", []

        play_list = args[0].strip().strip("'\"")

        # 1) Çağrının son argümanı JSON array ise altyazı oradan gelir
        subtitles: List[Subtitle] = []
        for arg in reversed(args):
            candidate = arg.strip()
            if not candidate.startswith("["):
                continue
            try:
                raw_subs = json.loads(candidate)
            except Exception:
                continue
            if not isinstance(raw_subs, list):
                continue
            subtitles = self._build_subtitles(raw_subs)
            break

        # 2) Kotlin'deki regex kalıbı (yedek)
        if not subtitles:
            for sub_url, sub_label in re.findall(
                r'"file":"((?:\\\\"|[^"])+)","label":"((?:\\\\"|[^"])+)"', html
            ):
                subtitles.append(Subtitle(
                    name=sub_label.replace("\\u0131", "ı").replace("\\u0130", "İ")
                                .replace("\\u00fc", "ü").replace("\\u00e7", "ç")
                                .replace("\\u011f", "ğ").replace("\\u015f", "ş"),
                    url=sub_url.replace("\\/", "/").replace("\\u0026", "&").replace("\\", ""),
                ))

        return play_list, subtitles

    @staticmethod
    def _build_subtitles(raw_subs: List[Any]) -> List[Subtitle]:
        subtitles: List[Subtitle] = []
        for item in raw_subs:
            if not isinstance(item, dict):
                continue
            sub_url = item.get("file")
            if not sub_url:
                continue
            subtitles.append(Subtitle(
                name=item.get("label") or item.get("lang") or "Türkçe",
                url=str(sub_url).replace("\\/", "/"),
            ))
        return subtitles

    @staticmethod
    def _parse_dub_token(html: str) -> Optional[str]:
        """Kotlin: ``,"<token>","Türkçe"`` -> dublaj alternatifi."""
        match = re.search(r",'([^']+)',\s*\"Türkçe\"", html)
        return match.group(1) if match else None

    # ------------------------------------------------------------------ #
    # Akış (source2.php -> m3u8)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _to_master(file_url: str) -> str:
        """Kotlin'deki ``m.php`` -> ``master.m3u8`` dönüşümü."""
        return file_url.replace("m.php", "master.m3u8")

    async def _stream_candidates(self, file_url: str, embed_url: str) -> List[Tuple[str, str]]:
        """(stream_url, referer) adaylarını öncelik sırasıyla üretir."""
        site_root = f"{urlparse(embed_url).scheme}://{urlparse(embed_url).netloc}/"
        referers = [file_url, embed_url, site_root]

        candidates: List[Tuple[str, str]] = []
        for stream in (self._to_master(file_url), file_url):
            for referer in referers:
                pair = (stream, referer)
                if pair not in candidates:
                    candidates.append(pair)
        return candidates

    async def _verify_stream(self, stream_url: str, referer: str) -> bool:
        """Adresin gerçekten bir HLS playlist döndürdüğünü doğrular."""
        try:
            resp = await self.client.get(stream_url, headers={
                "User-Agent": self.user_agent,
                "Referer": referer,
                "Origin": f"{urlparse(stream_url).scheme}://{urlparse(stream_url).netloc}",
            }, follow_redirects=True)
        except Exception as e:
            debug_log(f"[{type(self).__name__}] akış doğrulama hatası: {e!r}")
            return False

        return resp.status_code == 200 and resp.text.lstrip().startswith("#EXTM3U")

    async def _resolve_source(self, host_url: str, token: str, embed_url: str,
                              subtitles: List[Subtitle], label: str) -> Optional[ExtractResult]:
        """``source2.php`` -> playlist -> doğrulanmış tek ExtractResult."""
        data = await self._fetch_json(f"{host_url}/source2.php?v={token}", embed_url)
        if not data:
            return None
        if data.get("expired"):
            debug_log(f"[{type(self).__name__}] token süresi dolmuş")
            return None

        for entry in data.get("playlist") or []:
            if not isinstance(entry, dict):
                continue
            for source in entry.get("sources") or []:
                raw_file = str(source.get("file") or "")
                if not raw_file:
                    continue

                file_url = raw_file.replace("\\/", "/")
                if file_url.startswith("//"):
                    file_url = f"https:{file_url}"

                for stream_url, referer in await self._stream_candidates(file_url, embed_url):
                    if await self._verify_stream(stream_url, referer):
                        title = source.get("title") or source.get("description") or label
                        return ExtractResult(
                            name=f"{label} | {title}",
                            url=stream_url,
                            referer=referer,
                            headers={
                                "User-Agent": self.user_agent,
                                "Referer": referer,
                                "Origin": f"{urlparse(stream_url).scheme}://{urlparse(stream_url).netloc}",
                            },
                            subtitles=list(subtitles),
                        )

        return None

    # ------------------------------------------------------------------ #
    # Genel giriş noktası
    # ------------------------------------------------------------------ #

    async def resolve(
        self,
        url: str,
        referer: Optional[str] = None,
        extractor_name: Optional[str] = None,
    ) -> Optional[Union[ExtractResult, List[ExtractResult]]]:
        """``extract`` için ortak uygulama. ``extract`` yalnızca bunu çağırır."""
        site_referer = referer or ""
        label = extractor_name or getattr(self, "name", "ContentX")

        parsed = urlparse(url)
        host_url = f"{parsed.scheme}://{parsed.netloc}"

        debug_log(f"[{label}] resolve START url={url[:110]}")

        html = await self._fetch_text(url, site_referer)
        if not html or "openPlayer" not in html:
            if self._is_blocked(html or ""):
                print(f"[!] {label} sayfa Cloudflare tarafından engellendi (403/WAF): {url}")
            else:
                print(f"[!] {label} openPlayer bulunamadı (bağlantının süresi dolmuş olabilir): {url}")
            return None

        play_list, subtitles = self._parse_open_player(html)
        if not play_list:
            print(f"[!] {label} playList çözülemedi: {url}")
            return None

        results: List[ExtractResult] = []

        ana_kaynak = await self._resolve_source(host_url, play_list, url, subtitles, label)
        if ana_kaynak:
            results.append(ana_kaynak)

        # Dublaj alternatifi (Kotlin'deki "Türkçe" token'ı)
        dub_token = self._parse_dub_token(html)
        if dub_token and dub_token != play_list:
            dub = await self._resolve_source(host_url, dub_token, url, subtitles, f"{label} Dublaj")
            if dub:
                results.append(dub)

        if not results:
            print(f"[!] {label} oynatılabilir kaynak bulunamadı: {url}")
            return None

        debug_log(f"[{label}] resolve OK -> {len(results)} kaynak")
        return results[0] if len(results) == 1 else results
