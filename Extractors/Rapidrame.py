import base64
import json
import random
import re
import string
import urllib.parse
from typing import Any, Dict, List, Optional

from Core.Extractor.ExtractorBase import ExtractorBase
from Core.Extractor.ExtractorModels import ExtractResult, Subtitle
from Core.Extractor.DecoderHelpers import (
    JsUnpacker,
    resolve_player_stream,
    execute_dc_pipeline,
)
from Core.Helpers import debug_log, is_debug


class RapidrameExtractor(ExtractorBase):
    """
    HDFilmCehennemi Rapidrame Video Barındırıcı Çözücüsü.
    Desteklenenler: rapidrame, cehennempass.pw, dahili player sekmeleri (playerr, rplayer).
    """

    name = "Rapidrame"
    main_url = "https://rapidrame.com"
    domains = [
        "rapidrame",
        "cehennempass.pw",
        "playerr",
        "rplayer",
    ]

    def __init__(self):
        super().__init__()

    def can_handle_url(self, url: str) -> bool:
        """Close iframe'leri hariç Rapidrame ve türevi bağlantıları işler."""
        if "hdfilmcehennemi.mobi/video/embed/" in url:
            return False
        return any(domain in url for domain in self.domains)

    async def _fetch_page(self, url: str, headers: dict) -> str:
        """Embed/player sayfasını çeker. httpx → cloudscraper → curl_cffi sırasıyla dener.
        CF v3 challenge gibi zor korumalar için curl_cffi (TLS fingerprint) gerekiyor.
        """
        import asyncio

        debug_log(f"[{self.name}] _fetch_page START url={url[:100]}")
        text = ""
        try:
            resp = await self.client.get(url, headers=headers, follow_redirects=True)
            text = resp.text or ""
            debug_log(f"[{self.name}] httpx status={resp.status_code} len={len(text)}")
        except Exception as e:
            debug_log(f"[{self.name}] httpx exception: {e!r}")

        if text and len(text) > 200 and ("sources" in text or "jwplayer" in text or "function dc_" in text or "tracks:" in text):
            return text

        # 2. adım: cloudscraper (CF v1/v2 için yeterli)
        loop = asyncio.get_event_loop()
        try:
            cs_text = await loop.run_in_executor(
                None,
                lambda: self.cloudscraper.get(url, headers=headers, timeout=20).text,
            )
            debug_log(f"[{self.name}] cloudscraper len={len(cs_text)}")
            if cs_text and len(cs_text) > 200 and ("sources" in cs_text or "jwplayer" in cs_text or "function dc_" in cs_text or "tracks:" in cs_text):
                return cs_text
            text = text or cs_text
        except Exception as e:
            debug_log(f"[{self.name}] cloudscraper exception: {e!r}")

        # 3. adım: curl_cffi (CF v3 / Turnstile için gerekli; TLS fingerprint taklidi)
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

    def get_source_label(self, url: str) -> str:
        """Picker için kaynak etiketi üretir."""
        if "cehennempass.pw" in url:
            return "CehennemPass"
        return "Rapidrame"

    def _generate_random_cookie(self) -> str:
        return "".join(random.choices(string.ascii_letters + string.digits, k=16))

    async def _extract_cehennempass(self, url: str, referer: str) -> Optional[ExtractResult]:
        """CehennemPass download sayfasından video linklerini çıkarır."""
        video_id = url.split("/download/")[-1]
        if not video_id:
            return None

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Referer": f"https://cehennempass.pw/download/{video_id}",
            "X-Requested-With": "fetch",
            "authority": "cehennempass.pw",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        results = []
        for quality in ["high", "low"]:
            try:
                cookie = f"PHPSESSID={self._generate_random_cookie()}"
                resp = await self.client.post(
                    url="https://cehennempass.pw/process_quality_selection.php",
                    headers={**headers, "Cookie": cookie},
                    data={"video_id": video_id, "selected_quality": quality},
                    follow_redirects=True,
                )
                data = resp.json()
                video_url = data.get("download_link")
                if video_url:
                    video_url = video_url.replace(r"\/", "/")
                    quality_label = "Yüksek Kalite" if quality == "high" else "Düşük Kalite"
                    results.append({
                        "name": f"HDFilmCehennemi | CehennemPass ({quality_label})",
                        "url": video_url,
                        "referer": f"https://cehennempass.pw/download/{video_id}",
                        "headers": {
                            "User-Agent": headers["User-Agent"],
                            "Referer": f"https://cehennempass.pw/download/{video_id}",
                        },
                    })
            except Exception as e:
                print(f"[!] CehennemPass {quality} kalite hatası: {e}")

        if not results:
            return None

        r = results[0]
        return ExtractResult(
            name=r["name"],
            url=r["url"],
            referer=r["referer"],
            headers=r["headers"],
            subtitles=[],
        )

    async def extract(
        self, url: str, referer: Optional[str] = None, **kwargs: Any
    ) -> Optional[ExtractResult]:
        base_referer = referer or "https://www.hdfilmcehennemi.nl/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Referer": base_referer,
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        }

        # CehennemPass download sayfası ise özel işleme
        if "cehennempass.pw/download/" in url:
            return await self._extract_cehennempass(url, base_referer)

        # rapidrame_id parametresi varsa playerr URL'sine dönüştür
        if "?rapidrame_id=" in url:
            rapidrame_id = url.split("?rapidrame_id=")[1].split("&")[0].strip()
            url = f"https://www.hdfilmcehennemi.nl/playerr/{rapidrame_id}/"
        elif "playerr/" in url and not url.endswith("/"):
            url += "/"
        elif "rplayer/" in url and not url.endswith("/"):
            url += "/"

        # 1. Aşama: Link bir ara sekme ise (/152613 gibi), içindeki asıl iframe'i al
        if "video/embed" not in url and "playerr" not in url and "rplayer" not in url:
            try:
                resp = await self.client.get(url, headers=headers, follow_redirects=True)
                iframe_match = re.search(
                    r'<iframe[^>]+(?:data-src|src)=["\']([^"\']+)["\']', resp.text
                )
                if iframe_match:
                    url = self.fix_url(iframe_match.group(1))
                    if "?rapidrame_id=" in url:
                        rapidrame_id = url.split("?rapidrame_id=")[1].split("&")[0].strip()
                        url = f"https://www.hdfilmcehennemi.nl/playerr/{rapidrame_id}/"
                    elif ("playerr/" in url or "rplayer/" in url) and not url.endswith("/"):
                        url += "/"
                else:
                    return None
            except Exception as e:
                print(f"[!] {self.name} ara sekme çözümleme hatası ({url}): {e}")
                return None

        # 2. Aşama: Embed / Player sayfasını çek
        embed_headers = headers.copy()
        embed_headers["Referer"] = base_referer

        try:
            html_content = await self._fetch_page(url, embed_headers)

            # Dean Edwards Packer JS kontrolü ve açma
            unpacked_code = html_content
            if "eval(function(p,a,c,k,e," in html_content:
                try:
                    for em in re.finditer(r'eval\(function\(p,a,c,k,e,[rd]\)\{.*return p\}\(.*?\)\.split\(\'\|\'\)', html_content, re.DOTALL):
                        unpacked_code += "\n" + JsUnpacker.unpack(em.group(0))
                except Exception:
                    unpacked_code = JsUnpacker.unpack(html_content)

            # 3. Aşama: Akış (.m3u8 veya doğrudan video) linkini ayıkla
            stream_url = None

            # Metot 0: Obfuscation çözümleyici (v2 ve v1)
            stream_url = resolve_player_stream(html_content, unpacked_code)
            if stream_url:
                debug_log(f"[DEBUG {self.name}] Akış başarıyla çözüldü: {stream_url[:80]}")

            # Metot A: Dinamik dc_ pipeline çözümleyici (playerr / rplayer)
            if not stream_url:
                dc_func_match = re.search(r'function\s+(dc_[a-zA-Z0-9_]+)\s*\(', unpacked_code)
                if dc_func_match:
                    func_name = dc_func_match.group(1)
                    call_match = re.search(func_name + r'\s*\(\s*(\[.*?\])\s*\)', unpacked_code, re.DOTALL)
                    if call_match:
                        try:
                            parts = json.loads(call_match.group(1))
                        except Exception:
                            parts = re.findall(r'["\']([a-zA-Z0-9+/=]+)["\']', call_match.group(1))

                        func_code_match = re.search(
                            r'(function\s+' + func_name + r'\(.*?return\s+unmix\s*\}?)',
                            unpacked_code,
                            re.DOTALL,
                        )
                        if func_code_match:
                            try:
                                stream_url = execute_dc_pipeline(func_code_match.group(1), parts)
                            except Exception as e:
                                print(f"[!] {self.name} dc_ pipeline çalıştırma hatası: {e}")

            # Metot B: file: "..." veya source: "..."
            if not stream_url:
                file_match = re.search(
                    r'(?:file|source|src)\s*:\s*["\'](https?://[^"\']+\.m3u8[^"\']*)["\']',
                    unpacked_code,
                )
                if file_match:
                    stream_url = file_match.group(1)

            # Metot C: JSON sources dizisi
            if not stream_url:
                sources_match = re.search(
                    r'sources\s*:\s*(\[.*?\])\s*(?:,|\n|;)', unpacked_code, re.DOTALL
                )
                if sources_match:
                    try:
                        sources = json.loads(sources_match.group(1))
                        if sources and isinstance(sources, list):
                            stream_url = sources[0].get("file")
                    except Exception:
                        pass

            # Metot D: HTML5 <source> etiketi
            if not stream_url:
                source_tag = re.search(
                    r'<source[^>]+src=["\'](https?://[^"\']+\.m3u8[^"\']*)["\']',
                    unpacked_code,
                )
                if source_tag:
                    stream_url = source_tag.group(1)

            # Metot E: Metin içerisindeki saf m3u8 adresi
            if not stream_url:
                raw_m3u8 = re.search(
                    r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']', unpacked_code
                )
                if raw_m3u8:
                    stream_url = raw_m3u8.group(1)

            # Metot F: Base64 kodlu file_link
            if not stream_url:
                b64_match = re.search(r'file_link=\\"(.*?)\\"\;', unpacked_code)
                if b64_match:
                    try:
                        stream_url = base64.b64decode(b64_match.group(1)).decode("utf-8")
                    except Exception:
                        pass

            if not stream_url:
                return None

            # 4. Aşama: Altyazıları ayıkla
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
                                sub_url = f"https://rapidrame.com{sub_path}"
                            else:
                                sub_url = sub_path
                            subtitles.append(
                                Subtitle(
                                    name=t.get("label") or t.get("language") or "Türkçe",
                                    url=sub_url,
                                )
                            )
                except Exception as e:
                    print(f"[!] {self.name} altyazı ayrıştırma hatası: {e}")

            stream_referer = "https://rapidrame.com/"
            source_label = self.get_source_label(url)

            stream_headers = {
                "User-Agent": headers["User-Agent"],
                "Referer": stream_referer,
                "Origin": stream_referer.rstrip("/"),
            }

            return ExtractResult(
                name=f"HDFilmCehennemi | {source_label}",
                url=stream_url.replace(r"\/", "/"),
                referer=stream_referer,
                headers=stream_headers,
                subtitles=subtitles,
            )

        except Exception as e:
            print(f"[!] {self.name} extract hatası ({url}): {e}")
            return None


# Geriye dönük uyumluluk için alias
Rapidrame = RapidrameExtractor