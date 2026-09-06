import base64
import json
import random
import re
import string
import urllib.parse
from typing import Any, Dict, List, Optional

from Core.Extractor.ExtractorBase import ExtractorBase
from Core.Extractor.ExtractorModels import ExtractResult, Subtitle


class JsUnpacker:
    """Dean Edwards p.a.c.k.e.r şifreli JavaScript kodlarını çözer."""

    @staticmethod
    def unpack(packed: str) -> str:
        pattern = r"\}\('(.*?)'\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*'(.*?)'\.split\('\|'\)"
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


def execute_dc_pipeline(func_code: str, parts: list[str]) -> str:
    """Rapidrame ve HDFilmCehennemi dahili player'larındaki (dc_...) dinamik akış çözümleyiciyi yürütür."""
    result = "".join(parts)

    body_match = re.search(r'let result=value;(.*?)let unmix=', func_code, re.DOTALL)
    if not body_match:
        raise ValueError("Dönüştürme gövdesi bulunamadı")

    body = body_match.group(1)

    op_matches = re.finditer(r'result\s*=\s*(.*?);\s*(?=result\s*=|let\s+unmix|\Z)', body, re.DOTALL)

    for m in op_matches:
        expr = m.group(1).strip()
        if "reverse()" in expr:
            result = result[::-1]
        elif "replace" in expr:
            shift_match = re.search(r'\(o-base\+(\d+)\)%26\+base', expr)
            if shift_match:
                shift = int(shift_match.group(1))

                def rot(c, s=shift):
                    o = ord(c)
                    base = 65 if o <= 90 else 97
                    return chr((o - base + s) % 26 + base)

                result = re.sub(r"[a-zA-Z]", lambda ch: rot(ch.group(0)), result)
        elif "atob" in expr:
            result_bytes = result.encode("latin-1")
            result = base64.b64decode(result_bytes).decode("latin-1")

    unmix_match = re.search(r'\((\d+)%\(i\+(\d+)\)\)', func_code)
    if not unmix_match:
        raise ValueError("Unmix anahtar parametreleri bulunamadı")

    seed = int(unmix_match.group(1))
    offset = int(unmix_match.group(2))

    unmix = []
    for i, c in enumerate(result):
        char_code = ord(c)
        char_code = ((char_code - (seed % (i + offset))) % 256 + 256) % 256
        unmix.append(chr(char_code))

    return "".join(unmix)


class RapidrameExtractor(ExtractorBase):
    """
    HDFilmCehennemi & Rapidrame Video Barındırıcı Çözücüsü.
    Desteklenenler: hdfilmcehennemi.mobi, rapidrame, cehennempass.pw, dahili player sekmeleri (playerr, rplayer)
    """

    name = "Rapidrame"
    main_url = "https://hdfilmcehennemi.mobi"
    domains = [
        "rapidrame",
        "hdfilmcehennemi.mobi",
        "hdfilmcehennemi.nl",
        "hdfilmcehennemi.cx",
        "cehennempass.pw",
        "playerr",
        "rplayer",
    ]

    def __init__(self):
        super().__init__()

    def can_handle_url(self, url: str) -> bool:
        """Taban sınıftaki tekil main_url kontrolünü çoklu domain desteği ile genişletir."""
        return any(domain in url for domain in self.domains)

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

        # 2. Aşama: Embed / Player sayfasına git
        embed_domain = urllib.parse.urlparse(url).netloc or "rapidrame.com"
        embed_headers = headers.copy()
        embed_headers["Referer"] = base_referer

        try:
            embed_resp = await self.client.get(url, headers=embed_headers, follow_redirects=True)
            html_content = embed_resp.text

            # Dean Edwards Packer JS kontrolü ve açma
            unpacked_code = html_content
            if "eval(function(p,a,c,k,e," in html_content:
                eval_match = re.search(
                    r'eval\(function\(p,a,c,k,e,[rd]\)\{.*return p\}\(.*?\)\.split\(\'\|\'\)\)',
                    html_content,
                    re.DOTALL,
                )
                if eval_match:
                    unpacked_code = JsUnpacker.unpack(eval_match.group(0))
                else:
                    unpacked_code = JsUnpacker.unpack(html_content)

            # 3. Aşama: Akış (.m3u8 veya doğrudan video) linkini ayıkla
            stream_url = None

            # Metot A: Dinamik dc_ pipeline çözümleyici (playerr / rplayer)
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
                                sub_url = f"https://www.hdfilmcehennemi.nl{sub_path}"
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

            # Oynatıcı için HTTP başlıkları
            stream_headers = {
                "User-Agent": headers["User-Agent"],
                "Referer": "https://rapidrame.com/",
                "Origin": "https://rapidrame.com",
            }

            return ExtractResult(
                name=f"HDFilmCehennemi | Rapidrame",
                url=stream_url.replace(r"\/", "/"),
                referer="https://rapidrame.com/",
                headers=stream_headers,
                subtitles=subtitles,
            )

        except Exception as e:
            print(f"[!] {self.name} extract hatası ({url}): {e}")
            return None