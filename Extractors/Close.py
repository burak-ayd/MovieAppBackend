import json
import re
import urllib.parse
from typing import Any, Dict, List, Optional

from Core.Extractor.ExtractorBase import ExtractorBase
from Core.Extractor.ExtractorModels import ExtractResult, Subtitle
from Core.Extractor.DecoderHelpers import resolve_player_stream
from Core.Helpers import debug_log, is_debug


class CloseExtractor(ExtractorBase):
    """
    HDFilmCehennemi Close Video Barındırıcı Çözücüsü (closeplayer).
    hdfilmcehennemi.mobi/video/embed/ kaynaklarını çözümler.
    """

    name = "Close"
    main_url = "https://hdfilmcehennemi.mobi"
    domains = [
        "hdfilmcehennemi.mobi/video/embed/",
    ]

    def __init__(self):
        super().__init__()

    def can_handle_url(self, url: str) -> bool:
        return any(domain in url for domain in self.domains)

    def get_source_label(self, url: str) -> str:
        return "Close"

    async def _fetch_page(self, url: str, headers: dict) -> str:
        """Embed sayfasını çeker. httpx → cloudscraper → curl_cffi sırasıyla dener."""
        import asyncio

        debug_log(f"[{self.name}] _fetch_page START url={url[:100]}")
        text = ""
        try:
            resp = await self.client.get(url, headers=headers, follow_redirects=True)
            text = resp.text or ""
            debug_log(f"[{self.name}] httpx status={resp.status_code} len={len(text)}")
        except Exception as e:
            debug_log(f"[{self.name}] httpx exception: {e!r}")

        if text and len(text) > 200 and ("sources" in text or "jwplayer" in text or "tracks:" in text):
            return text

        # 2. adım: cloudscraper
        loop = asyncio.get_event_loop()
        try:
            cs_text = await loop.run_in_executor(
                None,
                lambda: self.cloudscraper.get(url, headers=headers, timeout=20).text,
            )
            debug_log(f"[{self.name}] cloudscraper len={len(cs_text)}")
            if cs_text and len(cs_text) > 200 and ("sources" in cs_text or "jwplayer" in cs_text or "tracks:" in cs_text):
                return cs_text
            text = text or cs_text
        except Exception as e:
            debug_log(f"[{self.name}] cloudscraper exception: {e!r}")

        # 3. adım: curl_cffi (CF TLS fingerprint taklidi)
        try:
            from curl_cffi.requests import Session as CffiSession

            def _do_cffi():
                with CffiSession(impersonate="chrome120") as s:
                    s.headers.update(headers)
                    r = s.get(url, timeout=20, allow_redirects=True)
                    return r.text

            cffi_text = await loop.run_in_executor(None, _do_cffi)
            debug_log(f"[{self.name}] curl_cffi len={len(cffi_text)}")
            if cffi_text and len(cffi_text) > 200:
                return cffi_text
        except Exception as e:
            debug_log(f"[{self.name}] curl_cffi exception: {e!r}")

        return text

    async def extract(
        self, url: str, referer: Optional[str] = None, **kwargs: Any
    ) -> Optional[ExtractResult]:
        base_referer = referer or "https://www.hdfilmcehennemi.nl/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Referer": base_referer,
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        }

        embed_domain = urllib.parse.urlparse(url).netloc or "hdfilmcehennemi.mobi"
        embed_headers = headers.copy()
        embed_headers["Referer"] = base_referer

        try:
            html_content = await self._fetch_page(url, embed_headers)
            stream_url = resolve_player_stream(html_content)

            if not stream_url:
                debug_log(f"[!] {self.name} stream_url bulunamadı: {url}")
                return None

            # Altyazıları ayıkla
            subtitles: List[Subtitle] = []
            tracks_match = re.search(
                r'tracks\s*:\s*(\[.*?\])\s*(?:,|\n|;)', html_content, re.DOTALL
            )
            if tracks_match:
                try:
                    tracks = json.loads(tracks_match.group(1))
                    for t in tracks:
                        if t.get("kind") in ["captions", "subtitles"] and t.get("file"):
                            sub_path = t.get("file").replace(r"\/", "/").replace("\\", "")
                            if sub_path.startswith("/"):
                                sub_url = f"https://hdfilmcehennemi.mobi{sub_path}"
                            else:
                                sub_url = sub_path
                            subtitles.append(
                                Subtitle(
                                    name=t.get("label") or t.get("language") or "Türkçe",
                                    url=sub_url,
                                )
                            )
                except Exception as e:
                    debug_log(f"[!] {self.name} altyazı ayrıştırma hatası: {e}")

            stream_referer = f"https://{embed_domain}/"
            stream_headers = {
                "User-Agent": headers["User-Agent"],
                "Referer": stream_referer,
                "Origin": stream_referer.rstrip("/"),
            }

            return ExtractResult(
                name="HDFilmCehennemi | Close",
                url=stream_url.replace(r"\/", "/"),
                referer=stream_referer,
                headers=stream_headers,
                subtitles=subtitles,
            )

        except Exception as e:
            print(f"[!] {self.name} extract hatası ({url}): {e}")
            return None


# Geriye dönük uyumluluk için alias
Close = CloseExtractor
